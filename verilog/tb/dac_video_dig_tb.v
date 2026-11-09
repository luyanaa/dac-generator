// SPDX-License-Identifier: Apache-2.0
//
// Self-checking testbench for dac_video_dig: launch handshake, settle window,
// and the guarantee that dout changes only on an accepted launch.
`timescale 1ns / 1ps
`default_nettype none

module dac_video_dig_tb;

    localparam integer SETTLE = 4;
    localparam integer CLK_PS = 10;   // 10 ns period, 100 MHz

    reg        clk = 1'b0;
    reg        rst_n = 1'b0;
    reg        stb = 1'b0;
    reg  [7:0] code = 8'd0;
    wire [7:0] dout;
    wire       valid;
    wire       ready;

    integer checks = 0;
    integer errors = 0;

    dac_video_dig #(.SETTLE_CYCLES(SETTLE)) dut (
        .clk(clk), .rst_n(rst_n), .stb(stb), .code(code),
        .dout(dout), .valid(valid), .ready(ready));

    always #(CLK_PS / 2.0) clk = ~clk;

    task chk(input cond, input [511:0] what);
        begin
            checks = checks + 1;
            if (!cond) begin
                errors = errors + 1;
                $display("FAIL: %0s (t=%0t dout=%0d valid=%b ready=%b)",
                         what, $time, dout, valid, ready);
            end
        end
    endtask

    // Wait for ready, then launch `c` and verify handshake, dout and the
    // settle window.  Leaves stb low.
    task launch_check(input [7:0] c);
        integer nlow;
        begin
            while (!ready) @(negedge clk);
            @(negedge clk);
            stb  = 1'b1;
            code = c;
            @(posedge clk);
            #1;
            chk(dout === c,    "dout latches the launched code");
            chk(valid === 1'b1, "valid pulses on launch");
            chk(ready === 1'b0, "ready drops on launch");
            @(negedge clk);
            stb = 1'b0;
            nlow = 1;
            @(posedge clk);
            #1;
            while (!ready) begin
                nlow = nlow + 1;
                @(posedge clk);
                #1;
            end
            chk(nlow == SETTLE, "ready low for exactly SETTLE_CYCLES");
            chk(dout === c,    "dout held through the settle window");
            @(posedge clk);
            #1;
            chk(valid === 1'b0, "valid is one cycle only");
        end
    endtask

    // Launch `c`, then assert stb with `ic` inside the settle window and prove
    // the request is ignored.
    task ignored_check(input [7:0] c, input [7:0] ic);
        begin
            while (!ready) @(negedge clk);
            @(negedge clk);
            stb  = 1'b1;
            code = c;
            @(posedge clk);
            #1;
            chk(dout === c,     "dout latches before ignored launch");
            chk(ready === 1'b0, "settle window is open");
            @(negedge clk);
            stb  = 1'b1;          // hold stb through the settle window
            code = ic;
            @(posedge clk);
            #1;
            chk(ready === 1'b0, "ready still low when stb is pushed");
            chk(valid === 1'b0, "ignored stb produces no valid");
            chk(dout === c,     "ignored stb does not change dout");
            @(negedge clk);
            stb = 1'b0;
            while (!ready) begin
                @(posedge clk);
                #1;
                chk(valid === 1'b0, "no valid while !ready");
            end
            chk(dout === c, "dout held through the settle window");
        end
    endtask

    integer i;
    reg [7:0] prev_dout;
    reg [7:0] rcode;

    initial begin
        // reset
        repeat (3) @(negedge clk);
        chk(dout === 8'd0,  "reset clears dout");
        chk(valid === 1'b0, "reset clears valid");
        chk(ready === 1'b1, "reset asserts ready");
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // all 256 codes, handshake-checked
        for (i = 0; i < 256; i = i + 1)
            launch_check(i[7:0]);

        // stb while !ready must be ignored
        for (i = 0; i < 16; i = i + 1)
            ignored_check(8'hA5 ^ i[7:0], 8'h5A ^ i[7:0]);

        // random traffic, including launches that land in settle windows
        for (i = 0; i < 1000; i = i + 1) begin
            rcode = $urandom;
            if (($urandom % 4) == 0) begin
                ignored_check(rcode, ~rcode);
            end else begin
                repeat ($urandom % 3) @(negedge clk);
                prev_dout = dout;
                launch_check(rcode);
                // dout may only differ if this launch changed the code
                chk(dout === rcode, "random launch result");
                if (rcode === prev_dout)
                    chk(dout === prev_dout, "same code stays stable");
            end
        end

        repeat (5) @(negedge clk);
        if (errors != 0) begin
            $display("FAIL %0d errors / %0d checks", errors, checks);
            $fatal(1, "dac_video_dig testbench failed");
        end
        $display("PASS %0d checks", checks);
        $finish;
    end

    // dout must only change on a launch: compare against the accepted stb
    // sampled one cycle earlier.
    reg prev_launch;
    reg [7:0] seen_dout;
    initial begin
        prev_launch = 1'b0;
        seen_dout = 8'd0;
    end
    always @(posedge clk) begin
        if (rst_n) begin
            if (dout !== seen_dout && !prev_launch) begin
                errors = errors + 1;
                $display("FAIL: dout changed without launch at t=%0t", $time);
            end
            seen_dout <= dout;
            prev_launch <= stb & ready;
        end else begin
            seen_dout <= 8'd0;
            prev_launch <= 1'b0;
        end
    end

    initial begin
        #2_000_000;
        $display("FAIL: timeout");
        $fatal(1, "timeout");
    end

endmodule
`default_nettype wire
