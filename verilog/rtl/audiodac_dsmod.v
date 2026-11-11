/*
 * AUDIOAC_DSMOD -- Delta-Sigma Modulator (1st/2nd Order) with Single-Bit Output
 *
 * SPDX-FileCopyrightText: 2021-2022 Harald Pretl (harald.pretl@jku.at)
 * Johannes Kepler University Linz, Institute for Integrated Circuits
 *
 * Parameters:
 *		BW 				... input data bitwidth
 *
 * Ports:
 *		data_i			... input data (UINT, 0..2^BW-1, midscale = silence)
 *		data_rd_o		... fetch next input data word (data feed-in driven
 *							by DS-modulator)
 *		ds_o, ds_n_o	... output bitstream (complimentary outputs)
 *
 *		rst_n_i			... reset (low active)
 *		clk_i			... clock of ds-modulator (must be OSR * input_data_rate),
 *							output bitstream rate = OSR * input_data_rate
 *
 *		mode_i			... select order of modulator (0 = 1st, 1 = 2nd)
 *		scale_i			... volume in 6 dB steps (0 = mute/off,
 *							15 = 0 dB/max, 14 = -6 dB, ..., 1 = -84 dB).
 *							Attenuation is done around midscale so the
 *							unsigned sample keeps its DC offset.
 *		osr_i			... oversampling ratio (OSR), 0=32/1=64/2=128/3=256
 *
 * Transfer function: for both orders the output 1-bit stream has an average
 * duty of data_i / 2^BW (0..100%), i.e. midscale = 50%.  The 1st-order path
 * is an exact unsigned accumulator.  The 2nd-order path is a CIFF
 * (cascade-of-integrators feed-forward) 1-bit modulator clocked at the full
 * output rate; its integrators are clamped so overload and DC-rail inputs
 * stay bounded.  The 2nd-order loop is stable up to about -1 dBFS; the
 * 1st-order path remains the full-scale (0 dBFS) mode.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 10ns / 1ns
`ifndef __AUDIODAC_DSMOD__
`define __AUDIODAC_DSMOD__

module audiodac_dsmod
#(
	parameter BW = 16
) (
	input 		[BW-1:0]	data_i,
	output wire				data_rd_o,
	output reg				ds_o,
	output wire				ds_n_o,

	input					rst_n_i,
	input					clk_i,

	input					mode_i,
	input 		[3:0]		scale_i,
	input		[1:0]		osr_i
);

	localparam	[BW-1:0]	DATA_MID	= {1'b1,{(BW-1){1'b0}}};
	// The CIFF state is held in BW+5 bits: enough for 6*2^BW plus the
	// feed-forward sum for any BW the interface accepts.  The 21-bit values
	// that used to be hard-coded were only correct for BW=16.
	localparam	integer		SW			= BW + 5;
	localparam	signed [SW-1:0]	MID_EXT		= (1 << (BW-1));   // FS/2
	localparam	signed [SW-1:0]	ISTATE_MAX	= (6 * (1 << BW)); // 6 * 2^BW

	// 1st-order accumulator (unsigned; carry == output)
	reg 		[BW-1:0]	accu1;

	// 2nd-order CIFF integrators (signed, fixed point in input LSBs)
	reg	signed	[SW-1:0]	i1;
	reg	signed	[SW-1:0]	i2;

	reg			[7:0]		fetch_ctr;		// clock divider by osr

	localparam	[7:0]		CTR_OSR_32  	=  8'd31;
	localparam	[7:0]		CTR_OSR_64  	=  8'd63;
	localparam	[7:0]		CTR_OSR_128 	=  8'd127;
	localparam	[7:0]		CTR_OSR_256 	=  8'd255;
	localparam	[1:0]		OSR_32  		= 2'd0;
	localparam	[1:0]		OSR_64  		= 2'd1;
	localparam	[1:0]		OSR_128 		= 2'd2;
	localparam	[1:0]		OSR_256 		= 2'd3;
	localparam				MODE_ORD1 		= 1'd0;
	localparam				MODE_ORD2 		= 1'd1;

	wire		[BW-1:0]	data_scaled;	// input data after volume control
	/* verilator lint_off UNUSEDSIGNAL */
	// Distances from midscale fit in BW bits; the MSB only exists because the
	// subtraction is evaluated in BW+1 bits and is therefore always zero.
	wire signed	[BW:0]		data_calc;		// signed attenuation around midscale
	/* verilator lint_on UNUSEDSIGNAL */
	wire signed	[BW:0]		x_s;			// centred 2nd-order input
	wire signed	[SW-1:0]	x_se;			// x_s sign-extended to state width
	wire signed	[SW-1:0]	s1;				// i1 + x
	wire signed	[SW-1:0]	u2;				// 2nd-order quantizer input
	wire						y2;				// 2nd-order quantizer output
	wire signed	[SW-1:0]	i1_pos, i1_neg;	// next i1 for +FS/2 / -FS/2 feedback
	wire signed	[SW-1:0]	i2_acc;			// i2 + i1
	wire signed	[SW-1:0]	i2_pos, i2_neg;	// next i2 for +FS/2 / -FS/2 feedback
	wire signed	[SW-1:0]	i1_nxt, i2_nxt;

	// provide out and out_n to make levelshifter easier
	assign ds_n_o = ~ds_o;

	// Volume in 6 dB steps: 0 = mute, 15 = 0 dB, 14 = -6 dB, ..., 1 = -84 dB.
	// Attenuate the signed distance from midscale so an unsigned sample does
	// not move its DC operating point when the volume changes.
	localparam integer ATT_MAX = (BW < 16) ? BW : 15;
	wire [3:0] att = (4'd15 - scale_i);
	wire [3:0] att_clamped = (att > ATT_MAX) ? ATT_MAX : att;
	assign data_calc = (($signed({1'b0,data_i}) - $signed({1'b0,DATA_MID}))
						>>> att_clamped) + $signed({1'b0,DATA_MID});
	assign data_scaled = (scale_i == 4'd0)  ? DATA_MID :
						 (scale_i == 4'd15) ? data_i   :
						 $unsigned(data_calc[BW-1:0]);

	// ---------------- 2nd-order CIFF modulator ----------------
	// x_s = data_scaled - FS/2;  u2 = x_s + i1 + i2;  y2 = (u2 >= 0)
	// i1 += x_s - fb;  i2 += i1 - fb;  fb = (y2 ? +FS/2 : -FS/2)
	// The input appears directly at the quantizer (feed-forward), so the
	// integrators only process the quantization error and stay small.
	//
	// The +FS/2 and -FS/2 possibilities are summed in parallel and only the
	// final mux depends on y2.  This keeps the combinational loop short
	// (two adders + compare + mux) so the design still closes timing.
	assign x_s  = $signed({1'b0,data_scaled}) - $signed({1'b0,DATA_MID});
	assign x_se = {{(SW-BW-1){x_s[BW]}}, x_s};
	assign s1   = i1 + x_se;
	assign u2   = s1 + i2;
	assign y2   = (u2 >= 0);
	assign i1_pos = s1 - MID_EXT;
	assign i1_neg = s1 + MID_EXT;
	assign i2_acc = i2 + i1;
	assign i2_pos = i2_acc - MID_EXT;
	assign i2_neg = i2_acc + MID_EXT;
	assign i1_nxt = y2 ? i1_pos : i1_neg;
	assign i2_nxt = y2 ? i2_pos : i2_neg;

	// the fetch counter controls the read of the next sample from the FIFO
	// the counter runs down so decoding is easier for different counter
	// cycles (reloads at 0)
	assign data_rd_o = (fetch_ctr == 8'd0);

	function signed [SW-1:0] sat_state;
		input signed [SW-1:0] v;
		begin
			if (v > ISTATE_MAX)
				sat_state = ISTATE_MAX;
			else if (v < -ISTATE_MAX)
				sat_state = -ISTATE_MAX;
			else
				sat_state = v;
		end
	endfunction

  	always @(posedge clk_i) begin
		if (!rst_n_i) begin
			// reset all registers
			accu1 <= {BW{1'b0}};
			i1 <= {SW{1'b0}};
			i2 <= {SW{1'b0}};
			ds_o <= 1'b0;
			fetch_ctr <= 8'b0;
		end else begin
			// sd-modulator is running

			if (fetch_ctr == 8'd0) begin
			// fetch_ctr finished, restart with proper cycle count
			// depending on osr
				case (osr_i)
					OSR_32:		fetch_ctr <= CTR_OSR_32;
					OSR_64:		fetch_ctr <= CTR_OSR_64;
					OSR_128:	fetch_ctr <= CTR_OSR_128;
					OSR_256:	fetch_ctr <= CTR_OSR_256;
					default:	fetch_ctr <= 8'bx;
				endcase
			end else
				//just keep counting down
				fetch_ctr <= fetch_ctr - 1'b1;

			if (mode_i == MODE_ORD1) begin
				// delta-sigma modulator 1st order: exact unsigned accumulator.
				// The carry is the 1-bit output, so the average duty is
				// data_scaled / 2^BW.
				{ds_o,accu1} <= data_scaled + accu1;

			end else if (mode_i == MODE_ORD2) begin
				// delta-sigma modulator 2nd order (CIFF, 1-bit, full rate).
				// The state clamp is a safety net for overload/DC-rail
				// inputs; it is inactive for normal audio levels.
				i1 <= sat_state(i1_nxt);
				i2 <= sat_state(i2_nxt);
				ds_o <= y2;
			end
		end
	end

endmodule // audiodac_dsmod

`endif
`default_nettype wire
