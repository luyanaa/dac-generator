// SPDX-License-Identifier: Apache-2.0
//
// Self-checking testbench for dac_wrap, the backend-selective wrapper.
//
// Two instances are elaborated side by side (the whole point of DAC_KIND):
//   * DAC_KIND=0 / pwmdac    : static level load, FIFO handshake, PWM duty
//   * DAC_KIND=1 / audiodac  : FIFO handshake, 1-bit bitstream, data_ack_o=0
//
// The wrapper's contract is the union of both backends, so the checks are:
//   - ds_n_o is the exact complement of ds_o on both kinds,
//   - the PWM kind accepts a static level and produces that duty,
//   - the DSM kind accepts a FIFO word and produces a toggling bitstream,
//   - the unused static-level port reads back as ack=0 on the DSM kind.
`timescale 1ns / 1ps
`default_nettype none

module dac_wrap_tb;

    localparam integer CLK_PS = 10;

    reg clk = 1'b0;
    reg rst_n = 1'b0;

    integer checks = 0, errors = 0;

    // ---------------- PWM kind (DAC_KIND = 0) ----------------
    reg  [15:0] p_fifo_i = 16'h0000;
    reg         p_fifo_rdy = 1'b0;
    wire        p_fifo_ack, p_fifo_full, p_fifo_empty;
    reg  [7:0]  p_data_i = 8'd0;
    reg         p_data_ld = 1'b0;
    wire        p_data_ack;
    wire        p_ds, p_dsn;

    dac_wrap #(.DAC_KIND(0), .BW(8), .CENTER_ALIGNED(0), .FIFO_SIZE(1)) wp (
        .fifo_i(p_fifo_i), .fifo_rdy_i(p_fifo_rdy),
        .fifo_ack_o(p_fifo_ack), .fifo_full_o(p_fifo_full),
        .fifo_empty_o(p_fifo_empty),
        .data_i(p_data_i), .data_ld_i(p_data_ld), .data_ack_o(p_data_ack),
        .rst_n_i(rst_n), .clk_i(clk),
        .mode_i(1'b0), .volume_i(4'd15), .osr_i(2'd2),
        .dith_i(1'b0), .center_i(1'b0),
        .ds_o(p_ds), .ds_n_o(p_dsn),
        .tst_fifo_loop_i(1'b0), .tst_sinegen_en_i(1'b0),
        .tst_sinegen_step_i(6'd0));

    // ---------------- DSM kind (DAC_KIND = 1) ----------------
    reg  [15:0] d_fifo_i = 16'h0000;
    reg         d_fifo_rdy = 1'b0;
    wire        d_fifo_ack, d_fifo_full, d_fifo_empty;
    wire        d_data_ack;
    wire        d_ds, d_dsn;

    dac_wrap #(.DAC_KIND(1), .BW(12), .CENTER_ALIGNED(0), .FIFO_SIZE(1)) wd (
        .fifo_i(d_fifo_i), .fifo_rdy_i(d_fifo_rdy),
        .fifo_ack_o(d_fifo_ack), .fifo_full_o(d_fifo_full),
        .fifo_empty_o(d_fifo_empty),
        .data_i(12'd0), .data_ld_i(1'b0), .data_ack_o(d_data_ack),
        .rst_n_i(rst_n), .clk_i(clk),
        .mode_i(1'b0), .volume_i(4'd15), .osr_i(2'd0),
        .dith_i(1'b0), .center_i(1'b0),
        .ds_o(d_ds), .ds_n_o(d_dsn),
        .tst_fifo_loop_i(1'b0), .tst_sinegen_en_i(1'b0),
        .tst_sinegen_step_i(6'd0));

    always #(CLK_PS / 2.0) clk = ~clk;

    task chk(input cond, input [511:0] what);
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("FAIL: %0s (t=%0t)", what, $time);
            end
        end
    endtask

    task pwm_load(input [7:0] c);
        begin
            while (p_data_ack) @(negedge clk);
            @(negedge clk);
            p_data_i = c; p_data_ld = 1'b1;
            // wait for the frame-end cycle (data_ack is high there), then the
            // latch edge itself
            while (!p_data_ack) @(negedge clk);
            @(posedge clk); #1;
            chk(p_data_ack === 1'b0, "pwm data_ack is one cycle wide");
            chk(wp.g_pwm.dac.duty_reg === c,
                "pwm duty latches at the frame end");
            @(negedge clk); p_data_ld = 1'b0;
        end
    endtask

    integer i, hi, tot;
    reg [15:0] w;

    initial begin
        repeat (3) @(negedge clk);
        chk(p_ds === 1'b0 || p_ds === 1'b1, "pwm ds is a bit after reset");
        chk(p_dsn === ~p_ds, "pwm ds_n is the complement after reset");
        chk(d_ds === 1'b0 || d_ds === 1'b1, "dsm ds is a bit after reset");
        chk(d_dsn === ~d_ds, "dsm ds_n is the complement after reset");
        chk(d_data_ack === 1'b0, "dsm static-level ack is tied low");
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // ---- PWM: static level -> duty, measured over one frame ----
        pwm_load(8'h40);
        chk(wp.g_pwm.dac.duty_reg === 8'h40,
            "pwm wrapper passes the static level to the duty register");
        hi = 0; tot = 0;
        while (tot < 256) begin
            @(posedge clk); #1;
            tot = tot + 1;
            if (p_ds) hi = hi + 1;
        end
        chk(hi >= 62 && hi <= 66, "pwm duty is 0x40 of 256 cycles");

        // ---- PWM: FIFO handshake through the wrapper ----
        w = 16'h7FFF;               // full scale positive
        p_fifo_i = w; p_fifo_rdy = 1'b1;
        i = 0;
        while (!p_fifo_ack && i < 20) begin
            @(posedge clk); #1;
            i = i + 1;
        end
        chk(i < 20, "pwm FIFO acknowledges through the wrapper");
        p_fifo_rdy = 1'b0;

        // ---- DSM: FIFO word -> toggling bitstream ----
        w = 16'hC000;
        d_fifo_i = w; d_fifo_rdy = 1'b1;
        i = 0;
        while (!d_fifo_ack && i < 40) begin
            @(posedge clk); #1;
            i = i + 1;
        end
        chk(i < 40, "dsm FIFO acknowledges through the wrapper");
        d_fifo_rdy = 1'b0;

        tot = 0;
        for (i = 0; i < 512; i = i + 1) begin
            @(posedge clk); #1;
            if (d_ds) tot = tot + 1;
            chk(d_dsn === ~d_ds, "dsm ds_n is the complement while running");
        end
        chk(tot > 64 && tot < 448, "dsm bitstream is toggling (not stuck)");

        // ---- the PWM backend keeps running while the DSM one does ----
        chk(p_dsn === ~p_ds, "pwm ds_n stays complementary");

        repeat (5) @(negedge clk);
        if (errors != 0) begin
            $display("FAIL %0d errors / %0d checks", errors, checks);
            $fatal(1, "dac_wrap testbench failed");
        end
        $display("PASS %0d checks", checks);
        $finish;
    end

    initial begin
        #5_000_000;
        $display("FAIL: timeout");
        $fatal(1, "timeout");
    end

endmodule
`default_nettype wire
