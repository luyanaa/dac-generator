/*
 * DAC_R2R_DIG -- Digital front end for the R-2R analog DAC leaf
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * The analog R-2R core (`analog/r2r`, hardened separately) is a plain
 * voltage-mode ladder: it wants one CMOS-level bit per rung and nothing else.
 * This macro is the standard-cell half of the pair — it registers the code so
 * the ladder never sees a glitched or skewed bus, and it can optionally act
 * as a small code source (ramp) for bench bring-up.
 *
 * It deliberately contains no thermometer decoder: an N-bit R-2R ladder is
 * driven directly by the N-bit code. The decoder/DEM machinery belongs to the
 * segmented topologies, not here.
 *
 * Parameters:
 *		N  ... code width, must match the analog leaf (default 8)
 *
 * Modes (mode_i, sampled with the same clock edge as the data):
 *		2'b00  register      code_o <= code_i
 *		2'b01  ramp          code_o <= code_o + 1  (wraps at 2^N, for benches)
 *		2'b10  hold          code_o frozen
 *		2'b11  register      reserved pattern, behaves as 2'b00
 *
 * Latency from code_i to code_o is exactly one clk_i cycle when en_i is high.
 * valid_o marks a cycle in which code_o was updated.
 */

`default_nettype none
`timescale 10ns / 1ns
`ifndef __DAC_R2R_DIG__
`define __DAC_R2R_DIG__

module dac_r2r_dig #(
	parameter N = 8
) (
	input  wire				clk_i,
	input  wire				rst_n_i,
	input  wire				en_i,
	input  wire	[1:0]		mode_i,
	input  wire	[N-1:0]		code_i,
	output reg	[N-1:0]		code_o,
	output reg				valid_o
);

	localparam [1:0] MODE_REG  = 2'b00;
	localparam [1:0] MODE_RAMP = 2'b01;
	localparam [1:0] MODE_HOLD = 2'b10;

	always @(posedge clk_i) begin
		if (!rst_n_i) begin
			code_o  <= {N{1'b0}};
			valid_o <= 1'b0;
		end else if (en_i) begin
			case (mode_i)
				MODE_RAMP: begin
					code_o  <= code_o + {{(N-1){1'b0}}, 1'b1};
					valid_o <= 1'b1;
				end
				MODE_REG: begin
					code_o  <= code_i;
					valid_o <= 1'b1;
				end
				MODE_HOLD: begin
					// Freeze the code; valid_o keeps its previous meaning.
				end
				default: begin
					code_o  <= code_i;
					valid_o <= 1'b1;
				end
			endcase
		end
	end

endmodule

`endif
