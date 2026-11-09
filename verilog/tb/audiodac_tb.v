// Self-checking testbench for the delta-sigma audio DAC.
//
//   cd verilog/tb && make
//
// Checks the observable DAC contract, not the internal implementation:
//   * 1st-order and 2nd-order DC transfer (0/25/50/75/100 % duty)
//   * 6 dB volume steps around midscale, mute at volume 0
//   * OSR fetch cadence (32/64/128/256)
//   * FIFO handshake
//   * sine-generator LUT (the Yosys/Icarus bit-order fix)
//   * complementary outputs
//
// Notes on the data path: the FIFO/audio path carries signed 16-bit samples
// (0x0000 = silence, 0x8000 = most negative).  audiodac.v converts them to
// unsigned by adding 0x8000 before the modulator, so the modulator input is
// (pushed_code + 0x8000) mod 65536 and the output duty is input/65536.
//
// The spectral performance (SNR/ENOB) is measured separately; see
// docs/delta_sigma.md.

`timescale 1ns/1ps

module audiodac_tb;

	reg clk = 1'b0;
	always #5 clk = ~clk;

	reg				rst_n = 1'b0;
	reg		[15:0]	fifo_i = 16'h0000;
	reg				fifo_rdy = 1'b0;
	wire			fifo_ack, fifo_full, fifo_empty;
	reg				mode_i = 1'b0;
	reg		[3:0]	volume_i = 4'd15;
	reg		[1:0]	osr_i = 2'd1;
	reg				tst_fifo_loop_i = 1'b0;
	reg				tst_sinegen_en_i = 1'b0;
	reg		[5:0]	tst_sinegen_step_i = 6'd1;
	wire			ds_o, ds_n_o;

	audiodac dut (
		.fifo_i(fifo_i), .fifo_rdy_i(fifo_rdy), .fifo_ack_o(fifo_ack),
		.fifo_full_o(fifo_full), .fifo_empty_o(fifo_empty),
		.rst_n_i(rst_n), .clk_i(clk),
		.mode_i(mode_i), .volume_i(volume_i), .osr_i(osr_i),
		.ds_o(ds_o), .ds_n_o(ds_n_o),
		.tst_fifo_loop_i(tst_fifo_loop_i),
		.tst_sinegen_en_i(tst_sinegen_en_i),
		.tst_sinegen_step_i(tst_sinegen_step_i)
	);

	integer errors = 0;
	integer checks = 0;
	integer i, high, want, got;

	// push one signed sample through the asynchronous FIFO interface
	task push(input [15:0] v);
		begin
			@(posedge clk); fifo_i = v; fifo_rdy = 1'b1;
			@(posedge clk);
			while (!fifo_ack) @(posedge clk);
			fifo_rdy = 1'b0;
			@(posedge clk);
		end
	endtask

	// Apply reset, push one sample, then count how many of ncyc posedges
	// have ds_o high.  A first-order accumulator gives exactly
	// (modulator_input * ncyc / 65536) highs for ncyc = 65536.
	task measure(input m, input [3:0] vol, input [15:0] code,
				 input integer ncyc, output integer highs);
		begin
			rst_n = 1'b0;
			repeat (8) @(posedge clk);
			mode_i = m; volume_i = vol; osr_i = 2'd1;
			rst_n = 1'b1;
			repeat (8) @(posedge clk);
			push(code);
			repeat (4096) @(posedge clk);
			highs = 0;
			for (i = 0; i < ncyc; i = i + 1) begin
				@(posedge clk); #1;
				if (ds_o) highs = highs + 1;
			end
		end
	endtask

	task expect_near(input [255:0] name, input integer value,
					 input integer want, input integer tol);
		begin
			checks = checks + 1;
			if (value < want - tol || value > want + tol) begin
				errors = errors + 1;
				$display("FAIL %0s: got %0d, want %0d +/- %0d",
						 name, value, want, tol);
			end else begin
				$display("ok   %0s: %0d (want %0d +/- %0d)", name, value, want, tol);
			end
		end
	endtask

	// signed sample -> modulator input code (audiodac.v adds 0x8000)
	function [15:0] mod_in(input [15:0] code);
		begin
			mod_in = code + 16'h8000;
		end
	endfunction

	// expected modulator input after the 6 dB volume control
	function [15:0] atten(input [15:0] code, input [3:0] vol);
		reg signed [16:0] s;
		reg [15:0] cin;
		begin
			cin = mod_in(code);
			if (vol == 4'd0)
				atten = 16'h8000;         // -inf dB: midscale
			else if (vol == 4'd15)
				atten = cin;
			else begin
				s = $signed({1'b0, cin}) - 17'sd32768;
				s = s >>> (4'd15 - vol);
				atten = (s + 17'sd32768) & 16'hFFFF;
			end
		end
	endfunction

	initial begin
		$dumpfile("audiodac_tb.vcd");
		$dumpvars(0, audiodac_tb);

		// ---- 1st-order DC transfer: exact ----
		measure(1'b0, 4'd15, 16'h8000, 65536, high); expect_near("1st code 0x8000 -> 0%",   high, 0,     0);
		measure(1'b0, 4'd15, 16'hC000, 65536, high); expect_near("1st code 0xC000 -> 25%",  high, 16384, 0);
		measure(1'b0, 4'd15, 16'h0000, 65536, high); expect_near("1st code 0x0000 -> 50%",  high, 32768, 0);
		measure(1'b0, 4'd15, 16'h4000, 65536, high); expect_near("1st code 0x4000 -> 75%",  high, 49152, 0);
		measure(1'b0, 4'd15, 16'h7FFF, 65536, high); expect_near("1st code 0x7FFF -> 100%", high, 65535, 0);

		// ---- 2nd-order DC transfer: unity gain, no offset ----
		measure(1'b1, 4'd15, 16'h8000, 65536, high); expect_near("2nd code 0x8000 -> 0%",   high, 0,     16);
		measure(1'b1, 4'd15, 16'hC000, 65536, high); expect_near("2nd code 0xC000 -> 25%",  high, 16384, 16);
		measure(1'b1, 4'd15, 16'h0000, 65536, high); expect_near("2nd code 0x0000 -> 50%",  high, 32768, 16);
		measure(1'b1, 4'd15, 16'h4000, 65536, high); expect_near("2nd code 0x4000 -> 75%",  high, 49152, 16);
		measure(1'b1, 4'd15, 16'h7FFF, 65536, high); expect_near("2nd code 0x7FFF -> 100%", high, 65535, 16);

		// ---- volume: 0 = mute, 15 = 0 dB, 14 = -6 dB ----
		measure(1'b0, 4'd0,  16'h7FFF, 65536, high); expect_near("vol=0 mute",        high, 32768, 0);
		measure(1'b0, 4'd14, 16'h7FFF, 65536, high); expect_near("vol=14 code 0x7FFF", high, atten(16'h7FFF,4'd14), 0);
		measure(1'b0, 4'd14, 16'h8000, 65536, high); expect_near("vol=14 code 0x8000", high, atten(16'h8000,4'd14), 0);
		measure(1'b0, 4'd14, 16'h0000, 65536, high); expect_near("vol=14 code 0x0000", high, atten(16'h0000,4'd14), 0);
		measure(1'b0, 4'd1,  16'h7FFF, 65536, high); expect_near("vol=1 code 0x7FFF",  high, atten(16'h7FFF,4'd1),  0);
		measure(1'b1, 4'd14, 16'h0000, 65536, high); expect_near("2nd vol=14 midscale",high, atten(16'h0000,4'd14), 16);

		// ---- OSR fetch cadence: one read every OSR clocks ----
		for (i = 0; i < 4; i = i + 1) begin
			rst_n = 1'b0; repeat (8) @(posedge clk);
			mode_i = 1'b1; volume_i = 4'd15; osr_i = i[1:0]; rst_n = 1'b1;
			@(posedge clk);
			while (!dut.dsmod0.data_rd_o) @(posedge clk);
			got = 0;
			@(posedge clk);
			while (!dut.dsmod0.data_rd_o && got < 600) begin
				got = got + 1;
				@(posedge clk);
			end
			expect_near("osr fetch interval", got, (1 << (5 + i)) - 1, 0);
		end

		// ---- FIFO handshake: ack must assert for each word, then drop ----
		rst_n = 1'b0; repeat (8) @(posedge clk); rst_n = 1'b1;
		mode_i = 1'b0; volume_i = 4'd15;
		for (i = 0; i < 4; i = i + 1) begin
			@(posedge clk); fifo_i = 16'h1000 + i; fifo_rdy = 1'b1;
			@(posedge clk);
			got = 0;
			while (!fifo_ack && got < 100) begin
				got = got + 1;
				@(posedge clk);
			end
			checks = checks + 1;
			if (fifo_ack !== 1'b1) begin
				errors = errors + 1;
				$display("FAIL fifo word %0d not acknowledged", i);
			end else
				$display("ok   fifo word %0d acknowledged", i);
			fifo_rdy = 1'b0;
			@(posedge clk);
			while (fifo_ack) @(posedge clk);
		end

		// ---- sine LUT: first eight entries advance one LUT step per read.
		// The reset value is 0, so the first observed sample is entry 1.
		rst_n = 1'b0; repeat (8) @(posedge clk);
		mode_i = 1'b1; volume_i = 4'd15; tst_sinegen_en_i = 1'b1;
		rst_n = 1'b1;
		@(posedge clk);
		for (i = 1; i <= 8; i = i + 1) begin
			while (!dut.dsmod0.data_rd_o) @(posedge clk);
			@(posedge clk); #1;
			case (i)
				1: want = 571;
				2: want = 1427;
				3: want = 2280;
				4: want = 3126;
				5: want = 3963;
				6: want = 4515;
				7: want = 5333;
				8: want = 6137;
				default: want = 0;
			endcase
			expect_near("sine LUT sample", $signed(dut.audio_sinegen), want, 0);
		end
		tst_sinegen_en_i = 1'b0;

		// ---- complementary outputs ----
		checks = checks + 1;
		if (ds_n_o !== ~ds_o) begin
			errors = errors + 1;
			$display("FAIL ds_n_o is not ~ds_o");
		end else
			$display("ok   ds_n_o == ~ds_o");

		$display("");
		if (errors == 0)
			$display("PASS: %0d checks", checks);
		else
			$display("FAIL: %0d/%0d checks failed", errors, checks);
		$finish;
	end

	// watchdog
	initial begin
		#200_000_000;
		$display("FAIL: timeout");
		$finish;
	end

endmodule
