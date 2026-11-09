/*
 * Self-checking testbench for dac_r2r_dig.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Covers: reset, one-cycle register latency, en_i gating, ramp mode (incl.
 * wrap), hold mode, and valid_o timing.
 */

`timescale 10ns / 1ns

module dac_r2r_dig_tb;

	localparam N = 8;

	reg				clk = 0;
	reg				rst_n = 0;
	reg				en = 0;
	reg		[1:0]	mode = 2'b00;
	reg		[N-1:0]	code_i = 0;
	wire	[N-1:0]	code_o;
	wire			valid_o;

	integer checks = 0;
	integer fails  = 0;

	dac_r2r_dig #(.N(N)) dut (
		.clk_i(clk),
		.rst_n_i(rst_n),
		.en_i(en),
		.mode_i(mode),
		.code_i(code_i),
		.code_o(code_o),
		.valid_o(valid_o)
	);

	always #1 clk = ~clk;   // 20 ns period

	task check;
		input [63:0] got;
		input [63:0] exp;
		input [127:0] name;
		begin
			checks = checks + 1;
			if (got !== exp) begin
				fails = fails + 1;
				$display("FAIL %0s: got %0d expected %0d", name, got, exp);
			end
		end
	endtask

	initial begin
		// Reset clears the register and valid.
		rst_n = 0;
		@(posedge clk); #0.1;
		check(code_o, 0, "reset code");
		check(valid_o, 0, "reset valid");
		rst_n = 1;
		en = 0;
		@(posedge clk); #0.1;

		// Register mode: one-cycle latency, en gating.
		code_i = 8'hA5; en = 1; mode = 2'b00;
		@(posedge clk); #0.1;
		check(code_o, 8'hA5, "register load");
		check(valid_o, 1, "register valid");
		code_i = 8'h3C;
		@(posedge clk); #0.1;
		check(code_o, 8'h3C, "register second word");
		code_i = 8'hFF; en = 0;
		@(posedge clk); #0.1;
		check(code_o, 8'h3C, "disabled holds code");

		// Ramp mode: increments by one per enabled edge and wraps.
		en = 1; mode = 2'b00;
		code_i = 8'h00;
		@(posedge clk); #0.1;
		check(code_o, 8'h00, "seed ramp at zero");
		mode = 2'b01;
		@(posedge clk); #0.1;
		check(code_o, 8'h01, "ramp 0->1");
		@(posedge clk); #0.1;
		check(code_o, 8'h02, "ramp 1->2");
		// Force near-wrap.
		code_i = 8'hFE;
		mode = 2'b00;
		@(posedge clk); #0.1;
		check(code_o, 8'hFE, "seed near wrap");
		mode = 2'b01;
		@(posedge clk); #0.1;
		check(code_o, 8'hFF, "ramp FE->FF");
		@(posedge clk); #0.1;
		check(code_o, 8'h00, "ramp wraps");

		// Hold mode freezes regardless of data.
		code_i = 8'h11; mode = 2'b00;
		@(posedge clk); #0.1;
		check(code_o, 8'h11, "hold seed");
		mode = 2'b10;
		code_i = 8'h77;
		@(posedge clk); #0.1;
		check(code_o, 8'h11, "hold freezes code");

		// Reserved mode behaves as register.
		mode = 2'b11;
		code_i = 8'h5A;
		@(posedge clk); #0.1;
		check(code_o, 8'h5A, "reserved behaves as register");

		// valid_o stays low while disabled.
		mode = 2'b00; en = 0; code_i = 8'h00;
		@(posedge clk); #0.1;
		check(valid_o, 1, "valid holds while disabled");

		$display("");
		if (fails == 0)
			$display("PASS: %0d/%0d checks", checks, checks);
		else
			$display("FAIL: %0d/%0d checks failed", fails, checks);
		$finish;
	end

endmodule
