// SPDX-License-Identifier: Apache-2.0
//
// Self-checking testbench for pwmdac:
//   * signed 16-bit FIFO word -> BW-bit duty (high bits, not the low slice),
//   * centre-aligned frame is 2^(BW+1) cycles (the wrapper shadow counter),
//   * 1-LSB dither saturates at full scale instead of wrapping,
//   * ds_n is the complement of ds.
`timescale 1ns / 1ps
`default_nettype none

module pwmdac_tb;

    localparam integer BW = 4;
    localparam integer CLK_PS = 10;

    reg clk = 1'b0;
    reg rst_n = 1'b0;

    reg  [15:0] fifo_i = 16'h0000;
    reg         fifo_rdy = 1'b0;
    wire        fifo_ack, fifo_full, fifo_empty;
    reg  [BW-1:0] data_i = 0;
    reg         data_ld = 1'b0;
    wire        data_ack;
    reg         dith = 1'b0;
    reg         center = 1'b0;
    wire        ds, dsn;

    integer checks = 0, errors = 0;
    wire ack_c;

    pwmdac #(.BW(BW), .CENTER_ALIGNED(0), .FIFO_SIZE(1)) dut (
        .fifo_i(fifo_i), .fifo_rdy_i(fifo_rdy), .fifo_ack_o(fifo_ack),
        .fifo_full_o(fifo_full), .fifo_empty_o(fifo_empty),
        .data_i(data_i), .data_ld_i(data_ld), .data_ack_o(data_ack),
        .rst_n_i(rst_n), .clk_i(clk), .dith_i(dith), .center_i(center),
        .ds_o(ds), .ds_n_o(dsn), .tst_fifo_loop_i(1'b0));

    pwmdac #(.BW(BW), .CENTER_ALIGNED(1), .FIFO_SIZE(0)) dut_c (
        .fifo_i(16'h0000), .fifo_rdy_i(1'b0), .fifo_ack_o(),
        .fifo_full_o(), .fifo_empty_o(),
        .data_i(data_i), .data_ld_i(data_ld), .data_ack_o(ack_c),
        .rst_n_i(rst_n), .clk_i(clk), .dith_i(1'b0), .center_i(center),
        .ds_o(), .ds_n_o(), .tst_fifo_loop_i(1'b0));

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

    task push(input [15:0] w);
        begin
            fifo_i = w;
            fifo_rdy = 1'b1;
            @(posedge clk); #1;
            while (!fifo_ack) begin
                @(posedge clk); #1;
            end
            fifo_rdy = 1'b0;
            @(posedge clk);
        end
    endtask

    function [BW-1:0] duty_of(input [15:0] w);
        begin
            duty_of = w[15 -: BW] + (1 << (BW - 1));
        end
    endfunction

    integer i, n;
    reg [15:0] words [0:5];

    initial begin
        words[0] = 16'h8000;   // most negative -> 0
        words[1] = 16'h0000;   // zero          -> mid
        words[2] = 16'h7FFF;   // most positive -> full
        words[3] = 16'hFFFF;   // -1            -> just below mid
        words[4] = 16'h4000;   // +quarter      -> 3/4
        words[5] = 16'hC000;   // -quarter      -> 1/4

        repeat (3) @(negedge clk);
        chk(ds === 1'b0 || ds === 1'b1, "ds is a bit");
        chk(dsn === ~ds, "ds_n is the complement");
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // FIFO async handshake: ack follows rdy (data is held stable by
        // the source; only rdy is synchronized).
        fifo_i = 16'h1234; fifo_rdy = 1'b1;
        @(posedge clk); #1;
        n = 0;
        while (!fifo_ack && n < 10) begin
            @(posedge clk); #1;
            n = n + 1;
        end
        chk(n < 10, "FIFO acknowledges the held word");
        fifo_rdy = 1'b0;

        // signed mapping: high BW bits + mid offset.  Force the FIFO output
        // so the combinational map is checked without the queue order.
        for (i = 0; i < 6; i = i + 1) begin
            force dut.fifo_data_w = words[i];
            #1;
            if (dut.duty_fifo !== duty_of(words[i]))
                $display("DBG i=%0d w=%h duty=%h exp=%h",
                         i, words[i], dut.duty_fifo, duty_of(words[i]));
            chk(dut.duty_fifo === duty_of(words[i]),
                "signed word maps to the high-bit duty");
            chk(dsn === ~ds, "ds_n is the complement");
            release dut.fifo_data_w;
        end

        // centre-aligned frame: 2^(BW+1) cycles between data_ack pulses
        center = 1'b1;
        data_i = 4'd8;
        data_ld = 1'b1;
        @(posedge clk); #1;
        while (ack_c) @(negedge ack_c);
        @(posedge ack_c); #1;
        n = 0;
        @(posedge clk); #1;
        while (!ack_c) begin
            n = n + 1;
            @(posedge clk); #1;
        end
        chk(n == (1 << (BW + 1)) - 1,
            "centre-aligned frame is 2^(BW+1) cycles");

        // dither saturates at full scale
        data_i = {BW{1'b1}};
        dith = 1'b1;
        while (data_ack) @(negedge data_ack);
        @(posedge data_ack);
        @(posedge clk); #1;
        chk(dut.duty_dith === {BW{1'b1}}, "dither saturates at full scale");

        repeat (3) @(negedge clk);
        if (errors != 0) begin
            $display("FAIL %0d errors / %0d checks", errors, checks);
            $fatal(1, "pwmdac testbench failed");
        end
        $display("PASS %0d checks", checks);
        $finish;
    end

    initial begin
        #2_000_000;
        $display("FAIL: timeout");
        $fatal(1, "timeout");
    end

endmodule
`default_nettype wire
