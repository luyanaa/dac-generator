// SPDX-License-Identifier: Apache-2.0
//
// Self-checking testbench for dac_video_dig:
//   * binary 8-bit / 255-cell expansion (GF180, IHP),
//   * thermometer 7-bit / 127-cell expansion (sky130),
//   * launch handshake, settle window, 25 MS/s accept rate at 100 MHz,
//   * dout_n is the exact complement of dout,
//   * dout changes only on an accepted launch.
`timescale 1ns / 1ps
`default_nettype none

module dac_video_dig_tb;

    localparam integer SETTLE = 3;    // 100 MHz -> 25 MS/s sustained
    localparam integer CLK_PS = 10;

    reg clk = 1'b0;
    reg rst_n = 1'b0;

    reg        stb_b = 1'b0;
    reg  [7:0] code_b = 8'd0;
    wire [254:0] dout_b, doutn_b;
    wire       valid_b, ready_b;

    reg        stb_t = 1'b0;
    reg  [6:0] code_t = 7'd0;
    wire [254:0] dout_t, doutn_t;
    wire       valid_t, ready_t;

    integer checks = 0;
    integer errors = 0;

    dac_video_dig #(.RESOLUTION(8), .ENCODING(0), .SETTLE_CYCLES(SETTLE))
        dut_b (.clk(clk), .rst_n(rst_n), .stb(stb_b), .code(code_b),
               .dout(dout_b), .dout_n(doutn_b), .valid(valid_b),
               .ready(ready_b));

    dac_video_dig #(.RESOLUTION(7), .ENCODING(1), .SETTLE_CYCLES(SETTLE))
        dut_t (.clk(clk), .rst_n(rst_n), .stb(stb_t), .code(code_t),
               .dout(dout_t), .dout_n(doutn_t), .valid(valid_t),
               .ready(ready_t));

    always #(CLK_PS / 2.0) clk = ~clk;

    function [254:0] expand_bin(input [7:0] c);
        integer j, k;
        begin
            for (j = 0; j < 255; j = j + 1) begin
                k = 0;
                while (j >= (1 << (k + 1)) - 1) k = k + 1;
                expand_bin[j] = c[k];
            end
        end
    endfunction

    function [254:0] expand_th(input [6:0] c);
        integer j;
        begin
            for (j = 0; j < 255; j = j + 1)
                expand_th[j] = (j < 127) ? (j < c) : 1'b0;
        end
    endfunction

    task chk(input cond, input [511:0] what);
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("FAIL: %0s (t=%0t)", what, $time);
            end
        end
    endtask

    task launch_bin(input [7:0] c);
        integer nlow;
        begin
            while (!ready_b) @(negedge clk);
            @(negedge clk);
            stb_b = 1'b1; code_b = c;
            @(posedge clk); #1;
            chk(dout_b === expand_bin(c), "binary dout latches the code");
            chk(doutn_b === ~dout_b, "binary dout_n is the complement");
            chk(valid_b === 1'b1, "binary valid pulses");
            chk(ready_b === 1'b0, "binary ready drops");
            @(negedge clk); stb_b = 1'b0;
            nlow = 1;
            @(posedge clk); #1;
            while (!ready_b) begin
                nlow = nlow + 1;
                @(posedge clk); #1;
            end
            chk(nlow == SETTLE, "binary ready low for SETTLE_CYCLES");
            chk(dout_b === expand_bin(c), "binary dout held");
            chk(doutn_b === ~dout_b, "binary dout_n held");
            @(posedge clk); #1;
            chk(valid_b === 1'b0, "binary valid is one cycle");
        end
    endtask

    task launch_th(input [6:0] c);
        integer nlow;
        begin
            while (!ready_t) @(negedge clk);
            @(negedge clk);
            stb_t = 1'b1; code_t = c;
            @(posedge clk); #1;
            chk(dout_t === expand_th(c), "thermo dout latches the code");
            chk(doutn_t === ~dout_t, "thermo dout_n is the complement");
            chk(valid_t === 1'b1, "thermo valid pulses");
            chk(ready_t === 1'b0, "thermo ready drops");
            @(negedge clk); stb_t = 1'b0;
            nlow = 1;
            @(posedge clk); #1;
            while (!ready_t) begin
                nlow = nlow + 1;
                @(posedge clk); #1;
            end
            chk(nlow == SETTLE, "thermo ready low for SETTLE_CYCLES");
            chk(dout_t === expand_th(c), "thermo dout held");
            chk(doutn_t === ~dout_t, "thermo dout_n held");
            @(posedge clk); #1;
            chk(valid_t === 1'b0, "thermo valid is one cycle");
        end
    endtask

    integer i, t0, t1;
    reg [7:0] rcode;

    initial begin
        repeat (3) @(negedge clk);
        chk(dout_b === {255{1'b0}}, "binary reset clears dout");
        chk(doutn_b === {255{1'b1}}, "binary reset sets dout_n");
        chk(dout_t === {255{1'b0}}, "thermo reset clears dout");
        chk(valid_b === 1'b0 && valid_t === 1'b0, "reset clears valid");
        chk(ready_b === 1'b1 && ready_t === 1'b1, "reset asserts ready");
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // binary: every code
        for (i = 0; i < 256; i = i + 1)
            launch_bin(i[7:0]);

        // thermometer: every code, including the 127-cell full scale
        for (i = 0; i < 128; i = i + 1)
            launch_th(i[6:0]);

        // sustained rate: back-to-back accepted launches must be
        // SETTLE+1 cycles apart (25 MS/s at 100 MHz with SETTLE=3).
        while (!ready_b) @(negedge clk);
        @(negedge clk); stb_b = 1'b1; code_b = 8'h11;
        @(posedge clk); t0 = $time; #1;
        @(negedge clk); stb_b = 1'b0;
        while (!ready_b) @(negedge clk);
        stb_b = 1'b1; code_b = 8'h22;
        @(posedge clk); t1 = $time; #1;
        chk((t1 - t0) == (SETTLE + 1) * CLK_PS,
            "binary accept interval is SETTLE+1 cycles");
        @(negedge clk); stb_b = 1'b0;

        // stb pushed inside the settle window is ignored
        while (!ready_t) @(negedge clk);
        @(negedge clk); stb_t = 1'b1; code_t = 7'h05;
        @(posedge clk); #1; @(negedge clk); stb_t = 1'b1; code_t = 7'h7a;
        @(posedge clk); #1;
        chk(valid_t === 1'b0, "thermo ignored stb produces no valid");
        chk(dout_t === expand_th(7'h05), "thermo ignored stb does not change dout");
        @(negedge clk); stb_t = 1'b0;
        while (!ready_t) @(posedge clk);

        // random binary traffic
        for (i = 0; i < 400; i = i + 1) begin
            rcode = $urandom;
            launch_bin(rcode);
        end

        repeat (5) @(negedge clk);
        if (errors != 0) begin
            $display("FAIL %0d errors / %0d checks", errors, checks);
            $fatal(1, "dac_video_dig testbench failed");
        end
        $display("PASS %0d checks", checks);
        $finish;
    end

    // dout may only change on an accepted launch.
    reg prev_launch_b, prev_launch_t;
    reg [254:0] seen_b, seen_t;
    initial begin
        prev_launch_b = 1'b0; prev_launch_t = 1'b0;
        seen_b = {255{1'b0}}; seen_t = {255{1'b0}};
    end
    always @(posedge clk) begin
        if (rst_n) begin
            if (dout_b !== seen_b && !prev_launch_b) begin
                errors = errors + 1;
                $display("FAIL: binary dout changed without launch");
            end
            if (dout_t !== seen_t && !prev_launch_t) begin
                errors = errors + 1;
                $display("FAIL: thermo dout changed without launch");
            end
            seen_b <= dout_b; seen_t <= dout_t;
            prev_launch_b <= stb_b & ready_b;
            prev_launch_t <= stb_t & ready_t;
        end else begin
            seen_b <= {255{1'b0}}; seen_t <= {255{1'b0}};
            prev_launch_b <= 1'b0; prev_launch_t <= 1'b0;
        end
    end

    initial begin
        #2_000_000;
        $display("FAIL: timeout");
        $fatal(1, "timeout");
    end

endmodule
`default_nettype wire
