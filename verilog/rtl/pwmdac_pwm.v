/*
 * PWMDAC_PWM -- Pulse-Width Modulator Core (Single-Bit Output)
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Reusable PWM modulator cell for the digital-PWM DAC backend. Emits a
 * periodic 1-bit stream on `ds_o` whose average equals data_i/2^BW. Drop-in
 * interchangeable with the delta-sigma modulator (`audiodac_dsmod`) at the
 * bitstream interface: both expose ds_o/ds_n_o on clk_i/rst_n_i.
 *
 * Parameters:
 *		BW 				... data bitwidth (default 12). f_pwm = f_clk / 2^BW,
 *							duty resolution = 2^-BW.
 *		CENTER_ALIGNED	... 1 = centre-aligned (up/down) PWM for lower EMI and
 *							half the output spectral line frequency; 0 = the
 *							cheaper left-aligned (sawtooth) PWM.
 *
 * Ports:
 *		data_i			... duty word, UINT [0 .. 2^BW-1]
 *		ds_o, ds_n_o	... PWM bitstream + complement
 *		rst_n_i			... async reset (low active)
 *		clk_i			... modulator clock; PWM period = 2^BW clk cycles
 */

`default_nettype none
`timescale 10ns / 1ns
`ifndef __PWMDAC_PWM__
`define __PWMDAC_PWM__

module pwmdac_pwm
#(
	parameter BW = 12,
	parameter CENTER_ALIGNED = 0
) (
	input 		[BW-1:0]	data_i,
	output reg				ds_o,
	output wire				ds_n_o,

	input					rst_n_i,
	input					clk_i
);

	reg			[BW-1:0]	cnt;			// free-running PWM counter
	reg						dir;			// 0 = up, 1 = down (center-aligned)

	assign ds_n_o = ~ds_o;

	// The compare uses the *current* duty word. data_i is only re-sampled by
	// the wrapper once per PWM period, so the pulse shape is never torn.
	always @(posedge clk_i or negedge rst_n_i) begin
		if (!rst_n_i) begin
			cnt		<= {BW{1'b0}};
			dir		<= 1'b0;
			ds_o	<= 1'b0;
		end else begin
			if (CENTER_ALIGNED) begin
				// up/down counter: period = 2^BW+1, spectrum centred at
				// f_clk/(2^(BW+1)) with symmetric edges -> lower EMI
				if (dir == 1'b0) begin
					if (cnt == {BW{1'b1}}) dir <= 1'b1;
					else cnt <= cnt + 1'b1;
				end else begin
					if (cnt == {BW{1'b0}}) dir <= 1'b0;
					else cnt <= cnt - 1'b1;
				end
			end else begin
				// simple sawtooth counter
				cnt <= cnt + 1'b1;
			end

			ds_o <= (cnt < data_i);
		end
	end

endmodule // pwmdac_pwm

`endif
`default_nettype wire
