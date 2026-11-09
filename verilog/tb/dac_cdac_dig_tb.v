/*
 * Self-checking testbench for dac_cdac_dig.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Covers: reset, the sample phase, the sample -> break -> drive sequence, all
 * 256 codes, a mid-conversion code change, and the invariants the analog
 * switches depend on:
 *   - b and bb are never both high (no VREFH/VREFL short through a bit),
 *   - in the drive phase b | bb is all ones and b & bb is zero,
 *   - every applied code has seen at least one all-off cycle first.
 *
 * Outputs are sampled on the falling edge, a half cycle after the registering
 * rising edge, so the checks never race the non-blocking assignments.
 */

`timescale 10ns / 1ns

module dac_cdac_dig_tb;

	localparam N = 8;

	reg				clk = 0;
	reg				rst_n = 0;
	reg				smp = 0;
	reg				stb = 0;
	reg		[N-1:0]	code = 0;
	wire	[N-1:0]	b;
	wire	[N-1:0]	bb;
	wire			smp_o;
	wire			pre;
	wire			valid;
	wire	[N-1:0]	code_q;

	integer checks = 0;
	integer fails  = 0;
	integer i;
	integer breaks = 0;

	dac_cdac_dig #(.N(N)) dut (
		.clk   (clk),
		.rst_n (rst_n),
		.smp   (smp),
		.stb   (stb),
		.code  (code),
		.b     (b),
		.bb    (bb),
		.smp_o (smp_o),
		.pre   (pre),
		.valid (valid),
		.code_q(code_q)
	);

	always #1 clk = ~clk;   // 20 ns period

	task check;
		input [63:0] got;
		input [63:0] want;
		input [255:0] what;
		begin
			checks = checks + 1;
			if (got !== want) begin
				fails = fails + 1;
				$display("FAIL %0s: got %0d want %0d (t=%0t)",
					what, got, want, $time);
			end
		end
	endtask

	// Invariants that must hold every sampled cycle.
	task invariants;
		reg [N-1:0] nbb;
		begin
			nbb = bb;
			if ((b & nbb) !== {N{1'b0}}) begin
				checks = checks + 1;
				fails = fails + 1;
				$display("FAIL b & bb overlap: b=%b bb=%b (t=%0t)",
					b, bb, $time);
			end
			if (smp_o && (b !== {N{1'b0}} || nbb !== {N{1'b0}})) begin
				checks = checks + 1;
				fails = fails + 1;
				$display("FAIL bit switch closed while sampling (t=%0t)", $time);
			end
		end
	endtask

	// One conversion trial: strobe `c`, expect one break cycle then drive.
	// Waits: negedge (drive state) -> posedge (break) -> negedge (check
	// break) -> posedge (drive the new code) -> negedge (check drive).
	task trial;
		input [N-1:0] c;
		reg [N-1:0] nb;
		begin
			@(negedge clk);
			code = c;
			stb = 1;
			@(posedge clk);      // S_DRIVE -> S_BREAK
			@(negedge clk);
			stb = 0;
			nb = ~c;
			check(b, {N{1'b0}}, "break b");
			check(bb, {N{1'b0}}, "break bb");
			check(valid, 0, "break valid");
			breaks = breaks + 1;
			invariants();
			@(posedge clk);      // S_BREAK -> S_DRIVE
			@(negedge clk);
			check(b, c, "drive b");
			check(bb, nb, "drive bb");
			check(valid, 1, "drive valid");
			check(code_q, c, "drive code_q");
			check(b | bb, {N{1'b1}}, "drive one gate per bit");
			invariants();
		end
	endtask

	initial begin
		// reset
		rst_n = 0;
		repeat (2) @(posedge clk);
		@(negedge clk);
		check(b, {N{1'b0}}, "b after reset");
		check(bb, {N{1'b0}}, "bb after reset");
		check(valid, 0, "valid after reset");
		check(pre, 0, "pre after reset");
		check(smp_o, 0, "smp_o after reset");
		invariants();

		rst_n = 1;
		@(posedge clk);
		@(negedge clk);
		check(valid, 0, "valid idle");
		invariants();

		// enter sampling
		smp = 1;
		@(posedge clk);
		@(negedge clk);
		check(smp_o, 1, "sample: smp_o");
		check(pre, 1, "sample: pre");
		check(b, {N{1'b0}}, "sample: b off");
		check(bb, {N{1'b0}}, "sample: bb off");
		invariants();

		// leave sampling: break, then drive the code latched while sampling
		code = 8'hA5;
		@(negedge clk);
		smp = 0;
		@(posedge clk);   // S_SAMPLE -> S_BREAK
		@(negedge clk);
		check(smp_o, 0, "post-sample smp_o");
		check(pre, 0, "post-sample pre");
		check(b, {N{1'b0}}, "post-sample break b");
		check(bb, {N{1'b0}}, "post-sample break bb");
		check(valid, 0, "post-sample break valid");
		invariants();
		@(posedge clk);   // S_BREAK -> S_DRIVE
		@(negedge clk);
		check(b, 8'hA5, "first drive after sample");
		check(bb, 8'h5A, "first drive after sample bb");
		check(valid, 1, "first drive valid");
		invariants();

		// every code through a break-before-make trial
		for (i = 0; i < 256; i = i + 1)
			trial(i[7:0]);

		// a trial while already driving, with a code change
		trial(8'hFF);
		trial(8'h00);

		if (fails == 0)
			$display("PASS dac_cdac_dig_tb: %0d checks, %0d break cycles",
				checks, breaks);
		else
			$display("FAIL dac_cdac_dig_tb: %0d/%0d checks failed",
				fails, checks);
		$finish;
	end

endmodule
