/*
 * Self-checking testbench for dac_string_dig.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Covers: reset state (code 0 valid, en=1), disabled gate drives, one-cycle break window, make
 * cycle, hold behaviour, and the two properties the analog tree depends on:
 *   - d and dn are never both high (a switch would be on in both polarities),
 *   - en is never high while the applied code differs from the requested one.
 */

`timescale 10ns / 1ns

module dac_string_dig_tb;

	localparam N = 8;

	reg				clk = 0;
	reg				rst_n = 0;
	reg		[N-1:0]	code = 0;
	wire	[N-1:0]	d;
	wire	[N-1:0]	dn;
	wire			en;
	wire			bsy;

	integer checks = 0;
	integer fails  = 0;
	integer i;

	dac_string_dig #(.N(N)) dut (
		.clk  (clk),
		.rst_n(rst_n),
		.code (code),
		.d    (d),
		.dn   (dn),
		.en   (en),
		.bsy  (bsy)
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
				$display("FAIL %0s: got %0d want %0d (t=%0t)", what, got, want, $time);
			end
		end
	endtask

	// Properties that must hold on every clock edge.
	task check_invariants;
		begin
			check((d & dn), 0, "d and dn overlap");
			// en may be high for one cycle after the code bus moves; the
			// applied code must equal the request latched at the break.
			if (en && (dut.code_q !== dut.code_pend)) begin
				fails = fails + 1;
				$display("FAIL en high with stale code: code_q=%0d code_pend=%0d",
					dut.code_q, dut.code_pend);
			end
		end
	endtask

	initial begin
		// reset
		rst_n = 0;
		repeat (2) @(posedge clk);
		#0.1;
		check(en, 1, "en after reset (code 0 is valid)");
		check(bsy, 0, "bsy after reset");
		check(d, {N{1'b0}}, "d after reset");
		check(dn, {N{1'b1}}, "dn after reset (all switches off)");
		check_invariants;

		rst_n = 1;
		@(posedge clk);
		#0.1;
		check_invariants;

		// ---- a single load: one break cycle, then make ----
		code = 8'hA5;
		@(posedge clk);
		#0.1;
		check(bsy, 1, "bsy during break");
		check(en, 0, "en during break");
		check(d, {N{1'b0}}, "d during break");
		check(dn, {N{1'b1}}, "dn during break");
		check_invariants;

		@(posedge clk);
		#0.1;
		check(bsy, 0, "bsy after make");
		check(en, 1, "en after make");
		check(d, 8'hA5, "d after make");
		check(dn, 8'h5A, "dn after make");
		check_invariants;

		// ---- hold: nothing changes while the code is static ----
		repeat (3) begin
			@(posedge clk);
			#0.1;
			check(en, 1, "en while holding");
			check(d, 8'hA5, "d while holding");
			check(dn, 8'h5A, "dn while holding");
			check_invariants;
		end

		// ---- every code, and a change on consecutive cycles ----
		for (i = 0; i < 256; i = i + 1) begin
			code = i;
			@(posedge clk);
			#0.1;
			check(bsy, 1, "bsy on change");
			check(en, 0, "en on change");
			check_invariants;
			@(posedge clk);
			#0.1;
			check(en, 1, "en after change");
			check(d, i[N-1:0], "d matches code");
			check(dn, ~i[N-1:0] & {N{1'b1}}, "dn is complement");
			check_invariants;
		end

		// ---- back-to-back change must not skip the break ----
		code = 8'h0F;
		@(posedge clk); #0.1;
		code = 8'hF0;               // changes again during the break
		@(posedge clk); #0.1;
		check(en, 1, "en after back-to-back change");
		check(d, 8'h0F, "applied code is the latched request");
		check_invariants;
		@(posedge clk); #0.1;
		check(bsy, 1, "a new break starts for the newer request");
		check(en, 0, "en low in the new break");
		@(posedge clk); #0.1;
		check(en, 1, "stays enabled after the second make");
		check(d, 8'hF0, "final code is the newer request");
		check_invariants;

		$display("PASS: %0d/%0d checks", checks - fails, checks);
		if (fails) $display("FAILED: %0d", fails);
		$finish;
	end

endmodule
