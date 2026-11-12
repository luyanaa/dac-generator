// SPDX-License-Identifier: Apache-2.0
//
// Digital half of the resistor-string (Kelvin) DAC leaf.
//
// The analog core is an 8-level binary transmission-gate tree over a 255-unit
// poly string.  Two things have to be guaranteed outside the analog core:
//
//   1. the tree is never driven straight from a moving code bus, and
//   2. a code change is break-before-make: all gates are off for at least one
//      clock before the new tap is connected, so two taps are never shorted
//      through the tree while the levels change at different times.
//
// `d[]` / `dn[]` are the non-overlapping gate drives (d is the n-FET gate, dn
// the p-FET gate of the same switch).  To turn a switch off both must be
// forced to (0, 1); forcing both low would turn the p-FET on, which is the
// classic bug this module exists to avoid.
//
//   en  : 1 while the tree is connected and the output is valid.  Reset
//         drives code 0 with en=1: zero is a valid tap, not a "no output"
//         state.  (An earlier version reset en=0 and then waited for a code
//         change, so a system that held code 0 after reset left the tree
//         disconnected forever.)
//   bsy : 1 during the one-cycle break window
//
// N is the number of tree levels (= bit count); the module is level-agnostic.
`timescale 1ns / 1ps
`default_nettype none

module dac_string_dig #(
    parameter N = 8
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [N-1:0] code,
    output reg  [N-1:0] d,
    output reg  [N-1:0] dn,
    output reg          en,
    output reg          bsy
);

    reg [N-1:0] code_q;    // code currently applied to the tree
    reg [N-1:0] code_pend; // code latched at the break, applied at make
    reg         pend;      // new code waiting for the break window

    wire change = (code != code_q);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            code_q    <= {N{1'b0}};
            code_pend <= {N{1'b0}};
            pend      <= 1'b0;
            en        <= 1'b1;   // code 0 is valid immediately after reset
            bsy       <= 1'b0;
        end else if (change && !pend) begin
            // Break: disconnect the tree and latch the request.  The code
            // bus may move during the break window; the request that caused
            // the break is the one that must be applied.
            code_pend <= code;
            pend      <= 1'b1;
            en        <= 1'b0;
            bsy       <= 1'b1;
        end else if (pend) begin
            // Make: apply the latched request and reconnect.
            code_q <= code_pend;
            pend   <= 1'b0;
            en     <= 1'b1;
            bsy    <= 1'b0;
        end
    end

    // Gate drives.  Disabled = (0, 1) for every switch.
    always @(*) begin
        d  = code_q & {N{en}};
        dn = ~(code_q & {N{en}});
    end

endmodule

`default_nettype wire
