/*
 * DAC_WRAP -- Backend-Selective Digital-DAC Wrapper (reusable seam)
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * A thin, fully-synthesizable wrapper that instantiates ONE of the two
 * digital-DAC backends behind a single, fixed interface. The host SoC /
 * user_project_wrapper talks to DAC_WRAP and selects the modulator at
 * elaboration with DAC_KIND — no RTL edits needed to swap architectures.
 *
 *   DAC_KIND = 0 : `pwmdac`    (PWM + RC — arch #1, simplest/cheapest)
 *   DAC_KIND = 1 : `audiodac`  (1st/2nd-order ΔΣ + RC — arch #2, higher ENOB)
 *
 * The exposed contract is the union of both backends' ports:
 *   - streaming input   : fifo_i/fifo_rdy_i/fifo_ack_o/fifo_full_o/fifo_empty_o
 *   - static level      : data_i/data_ld_i/data_ack_o   (pwmdac only; ignored on ΔΣ)
 *   - config            : mode_i/volume_i/osr_i          (ΔΣ only; ignored on PWM)
 *                         dith_i                         (PWM only; ignored on ΔΣ)
 *   - output            : ds_o/ds_n_o -> GPIO -> RC filter
 *
 * Because the unused config inputs are constant-folded at synthesis, selecting
 * one backend costs nothing extra — yosys prunes the unreachable logic.
 *
 * Parameters:
 *   DAC_KIND        ... 0 = pwmdac, 1 = audiodac (default 0)
 *   BW              ... data width (12 for pwmdac; audiodac is fixed 16)
 *   CENTER_ALIGNED  ... pwmdac centre-aligned PWM
 *   FIFO_SIZE       ... input FIFO depth 2^N
 */

`default_nettype none
`timescale 10ns / 1ns
`ifndef __DAC_WRAP__
`define __DAC_WRAP__

`ifdef SIM_PYTHON
	`include "../dig/rtl/pwmdac.v"
	`include "../dig/rtl/audiodac.v"
 `else
	`include "pwmdac.v"
	`include "audiodac.v"
`endif

module dac_wrap #(
	parameter DAC_KIND = 0,			// 0=pwm, 1=delta-sigma
	parameter BW = 12,
	parameter CENTER_ALIGNED = 0,
	parameter FIFO_SIZE = 5
) (
`ifdef USE_POWER_PINS
	inout 				vccd1,
	inout 				vssd1,
`endif
	// streaming input (common)
	input		[15:0]	fifo_i,
	input				fifo_rdy_i,
	output wire			fifo_ack_o,
	output wire			fifo_full_o,
	output wire			fifo_empty_o,
	// static level (pwmdac)
	input		[BW-1:0]	data_i,
	input				data_ld_i,
	output wire			data_ack_o,
	// housekeeping
	input				rst_n_i,
	input				clk_i,
	// config (subset used per backend)
	input				mode_i,		// ΔΣ: 0=1st,1=2nd order
	input		[3:0]	volume_i,	// ΔΣ: 0=off .. 15=max
	input		[1:0]	osr_i,		// ΔΣ: 32/64/128/256
	input				dith_i,		// PWM: +1 LSB dither
	input				center_i,	// PWM: centre-aligned
	// bitstream output
	output wire			ds_o,
	output wire			ds_n_o,
	// test
	input				tst_fifo_loop_i,
	input				tst_sinegen_en_i,
	input		[5:0]	tst_sinegen_step_i
);

	generate
		if (DAC_KIND == 1) begin : g_dsm
			// ---- architecture #2: delta-sigma ----
			audiodac dac (
			`ifdef USE_POWER_PINS
				.vccd1(vccd1), .vssd1(vssd1),
			`endif
				.fifo_i(fifo_i),
				.fifo_rdy_i(fifo_rdy_i),
				.fifo_ack_o(fifo_ack_o),
				.fifo_full_o(fifo_full_o),
				.fifo_empty_o(fifo_empty_o),
				.rst_n_i(rst_n_i),
				.clk_i(clk_i),
				.mode_i(mode_i),
				.volume_i(volume_i),
				.osr_i(osr_i),
				.ds_o(ds_o),
				.ds_n_o(ds_n_o),
				.tst_fifo_loop_i(tst_fifo_loop_i),
				.tst_sinegen_en_i(tst_sinegen_en_i),
				.tst_sinegen_step_i(tst_sinegen_step_i)
			);
			assign data_ack_o = 1'b0;
		end else begin : g_pwm
			// ---- architecture #1: PWM ----
			pwmdac #(
				.BW(BW),
				.CENTER_ALIGNED(CENTER_ALIGNED),
				.FIFO_SIZE(FIFO_SIZE)
			) dac (
			`ifdef USE_POWER_PINS
				.vccd1(vccd1), .vssd1(vssd1),
			`endif
				.fifo_i(fifo_i),
				.fifo_rdy_i(fifo_rdy_i),
				.fifo_ack_o(fifo_ack_o),
				.fifo_full_o(fifo_full_o),
				.fifo_empty_o(fifo_empty_o),
				.data_i(data_i),
				.data_ld_i(data_ld_i),
				.data_ack_o(data_ack_o),
				.rst_n_i(rst_n_i),
				.clk_i(clk_i),
				.dith_i(dith_i),
				.center_i(center_i),
				.ds_o(ds_o),
				.ds_n_o(ds_n_o),
				.tst_fifo_loop_i(tst_fifo_loop_i)
			);
		end
	endgenerate

endmodule // dac_wrap

`endif
`default_nettype wire
