/*
 * Self-checking testbench for dac_csteer_dig.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Covers: reset state, registered thermometer decode against a reference
 * model, binary pass-through, the DWA pointer recurrence, and the property
 * DEM exists for: over 15 samples of a constant code with k unary cells,
 * every one of the 15 physical cells is selected exactly k times.
 */

`timescale 10ns / 1ns

module dac_csteer_dig_tb;

	localparam N_UNARY = 15;

	reg			clk = 0;
	reg			rst_n = 0;
	reg			stb = 0;
	reg	[7:0]	code = 0;
	wire [14:0]	th;
	wire [3:0]	b;
	wire [3:0]	ptr;
	wire		valid;
	wire [7:0]	code_q;

	integer checks = 0;
	integer fails  = 0;
	integer i, k, s;
	integer counts [0:14];

	dac_csteer_dig dut (
		.clk   (clk),
		.rst_n (rst_n),
		.stb   (stb),
		.code  (code),
		.th    (th),
		.b     (b),
		.ptr   (ptr),
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

	// Reference rotated-thermometer model: cell j is on when its clockwise
	// distance from ptr is below n_act.
	function [14:0] ref_decode;
		input [7:0] c;
		input [3:0] p;
		integer j, d;
		begin
			ref_decode = 15'b0;
			for (j = 0; j < N_UNARY; j = j + 1) begin
				d = (j >= p) ? (j - p) : (j + N_UNARY - p);
				ref_decode[j] = (d < c[7:4]);
			end
		end
	endfunction

	function [3:0] next_ptr;
		input [3:0] p;
		input [3:0] n;
		integer sum;
		begin
			sum = p + n;
			next_ptr = sum % N_UNARY;
		end
	endfunction

	function integer popcount;
		input [14:0] v;
		integer j;
		begin
			popcount = 0;
			for (j = 0; j < N_UNARY; j = j + 1)
				popcount = popcount + v[j];
		end
	endfunction

	// One strobe: latch `c` into the DAC and check the registered outputs
	// against the pre-update pointer.
	task strobe;
		input [7:0] c;
		reg [3:0] p0;
		reg [14:0] want_th;
		begin
			p0 = ptr;
			want_th = ref_decode(c, p0);
			code = c;
			stb = 1;
			@(posedge clk);
			#0.1;
			stb = 0;
			check(valid, 1, "valid after strobe");
			check(th, want_th, "thermometer decode");
			check(b, c[3:0], "binary field");
			check(code_q, c, "latched code");
			check(ptr, next_ptr(p0, c[7:4]), "DWA pointer advance");
			check(popcount(th), c[7:4], "thermometer cell count");
			@(posedge clk);
			#0.1;
			check(valid, 0, "valid is one cycle");
			check(th, want_th, "output held while not strobing");
		end
	endtask

	initial begin
		// reset
		rst_n = 0;
		repeat (2) @(posedge clk);
		#0.1;
		check(th, 15'b0, "th after reset");
		check(b, 4'h0, "b after reset");
		check(ptr, 4'd0, "ptr after reset");
		check(valid, 0, "valid after reset");

		rst_n = 1;
		@(posedge clk);
		#0.1;
		check(valid, 0, "valid idle");

		// all 256 codes through the reference model
		for (i = 0; i < 256; i = i + 1)
			strobe(i[7:0]);

		// full-scale unary: all 15 cells on regardless of pointer
		strobe(8'hFF);
		check(th, 15'h7FFF, "full-scale thermometer");

		// DWA fairness: k unary cells, 15 samples, every cell exactly k times
		for (k = 1; k <= 7; k = k + 1) begin
			for (i = 0; i < N_UNARY; i = i + 1)
				counts[i] = 0;
			// reset the pointer so the test is deterministic
			@(negedge clk);
			dut.ptr = 4'd0;
			for (s = 0; s < N_UNARY; s = s + 1) begin
				strobe(k[3:0] << 4);
				for (i = 0; i < N_UNARY; i = i + 1)
					counts[i] = counts[i] + th[i];
			end
			for (i = 0; i < N_UNARY; i = i + 1) begin
				checks = checks + 1;
				if (counts[i] !== k) begin
					fails = fails + 1;
					$display("FAIL DWA k=%0d cell %0d: %0d uses",
						k, i, counts[i]);
				end
			end
		end

		if (fails == 0)
			$display("PASS dac_csteer_dig_tb: %0d checks", checks);
		else
			$display("FAIL dac_csteer_dig_tb: %0d/%0d checks failed",
				fails, checks);
		$finish;
	end

endmodule
