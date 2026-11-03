/*
 * PWMDAC -- Fully-Digital PWM DAC (Single-Bit Output)
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Architecture #1 of the reusable digital-DAC set (see DAC_ARCHITECTURES.md):
 * a periodic PWM modulator followed by an off/on-die RC low-pass. Simplest
 * all-digital DAC — one GPIO drives the bitstream, one R+C rebuilds the level.
 *
 * Interface mirrors `audiodac` so the two backends are swappable in
 * user_project_wrapper: same FIFO-in hand-shake, same ds_o/ds_n_o output,
 * same clk_i/rst_n_i. The duty word may instead be latched from a static
 * register feed (data_i + data_ld_i) for a register-driven DC DAC.
 *
 * The PWM period is 2^BW clk_i cycles; place fc(RC) well below
 * f_clk/2^BW. e.g. BW=12, clk=10MHz -> f_pwm≈2.4kHz, RC fc≈100-300Hz.
 *
 * Parameters:
 *		BW 				... resolution (default 12 -> 0.024% LSB)
 *		CENTER_ALIGNED	... 1 for lower-EMI centre-aligned PWM
 *		FIFO_SIZE		... input FIFO depth 2^N (0 = bypass FIFO)
 */

`default_nettype none
`timescale 10ns / 1ns
`ifndef __PWMDAC__
`define __PWMDAC__

`ifdef SIM_PYTHON
	`include "../dig/rtl/pwmdac_pwm.v"
	`include "../dig/rtl/audiodac_fifo.v"
 `else
	`include "pwmdac_pwm.v"
	`include "audiodac_fifo.v"
`endif

module pwmdac #(
	parameter BW = 12,
	parameter CENTER_ALIGNED = 0,
	parameter FIFO_SIZE = 5		// 0 bypasses the input FIFO
) (
`ifdef USE_POWER_PINS
	inout 				vccd1,
	inout 				vssd1,
`endif

	// --- streaming input (same as audiodac) ---
	input		[15:0]	fifo_i,		// signed INT, mapped to UINT internally
	input				fifo_rdy_i,
	output wire			fifo_ack_o,
	output wire			fifo_full_o,
	output wire			fifo_empty_o,

	// --- direct level input (static DC via config reg) ---
	input		[BW-1:0]	data_i,
	input				data_ld_i,	// level-select: 1 = use data_i, 0 = use FIFO
	output wire			data_ack_o,	// high the clk a new duty is committed

	// --- housekeeping ---
	input				rst_n_i,
	input				clk_i,

	// --- config ---
	input				dith_i,		// 1 = add 1 LSB (crude dither)
	input				center_i,	// reserved: centre-aligned select

	// --- bitstream output ---
	output wire			ds_o,		// PWM bitstream -> GPIO -> RC filter
	output wire			ds_n_o,		// complementary

	// --- test ---
	input				tst_fifo_loop_i
);

	localparam	[BW-1:0]	DATA_MID = {1'b1,{(BW-1){1'b0}}};

	wire		[15:0]		fifo_data_w;
	wire		[BW-1:0]	duty_fifo;
	wire					fifo_rd, period_end;
	reg			[BW-1:0]	shadow_cnt;		// tracks the PWM frame boundary
	reg			[BW-1:0]	duty_reg;		// period-aligned duty latch
	wire		[BW-1:0]	duty_sel;

	// ------------------------------------------------------------------
	// Input source: FIFO (streaming) or direct register level.
	// ------------------------------------------------------------------
	generate
		if (FIFO_SIZE > 0) begin : g_fifo
			audiodac_fifo
				#(16, FIFO_SIZE, 1)
				fifo0 (
					.fifo_indata_i(fifo_i),
					.fifo_indata_rdy_i(fifo_rdy_i),
					.fifo_indata_ack_o(fifo_ack_o),
					.fifo_full_o(fifo_full_o),
					.fifo_empty_o(fifo_empty_o),
					.fifo_outdata_o(fifo_data_w),
					.fifo_outdata_rd_i(fifo_rd),
					.rst_n_i(rst_n_i),
					.clk_i(clk_i),
					.tst_fifo_loop_i(tst_fifo_loop_i)
				);
		end else begin : g_nofifo
			assign fifo_data_w  = 16'b0;
			assign fifo_ack_o   = 1'b0;
			assign fifo_full_o  = 1'b1;
			assign fifo_empty_o = 1'b0;
		end
	endgenerate

	// map the 16b signed-INT FIFO word onto the BW-bit unsigned duty
	assign duty_fifo = fifo_data_w[BW-1:0] + DATA_MID;

	// select input source (register feed wins when data_ld_i is held high)
	assign duty_sel = data_ld_i ? data_i : duty_fifo;

	// commit the selected duty once per PWM frame so a changing input cannot
	// slice a pulse in two; the core's counter is internal, so shadow it here.
	always @(posedge clk_i or negedge rst_n_i) begin
		if (!rst_n_i) begin
			shadow_cnt <= {BW{1'b0}};
			duty_reg   <= DATA_MID;
		end else begin
			shadow_cnt <= shadow_cnt + 1'b1;
			if (period_end)
				duty_reg <= duty_sel;
		end
	end
	assign period_end = (shadow_cnt == {BW{1'b1}});
	assign data_ack_o = period_end;

	// the PWM core does the counter+compare
	pwmdac_pwm
		#(.BW(BW), .CENTER_ALIGNED(CENTER_ALIGNED))
		pwm0 (
			.data_i(dith_i ? duty_reg + 1'b1 : duty_reg),
			.ds_o(ds_o),
			.ds_n_o(ds_n_o),
			.rst_n_i(rst_n_i),
			.clk_i(clk_i)
		);

	// fetch the next FIFO word once per frame (when one is waiting)
	generate
		if (FIFO_SIZE > 0) begin : g_fiford
			assign fifo_rd = period_end & ~fifo_empty_o;
		end else begin : g_nofiford
			assign fifo_rd = 1'b0;
		end
	endgenerate

endmodule // pwmdac

`endif
`default_nettype wire
