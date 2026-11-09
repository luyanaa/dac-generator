// SPDX-License-Identifier: Apache-2.0
//
// Digital half of the unit-current-steering DAC leaf (8 bit, 4+4).
//
// The analog core is 15 unary PMOS current cells (16 LSB each) plus a 4-bit
// binary field (8/4/2/1 LSB).  This module owns the two things that must not
// be left to the analog side:
//
//   1. thermometer decode of the 4 MSBs, so only one cell changes per code
//      step at a major carry, and
//   2. first-order data-weighted averaging (DWA): the unary field is rotated
//      by the number of cells it used, so over 15 samples every cell carries
//      the same average current and the per-cell gain error is high-pass
//      shaped out of the signal band.
//
// `th[]` is indexed by physical cell, not by code: th[j] is high when cell j
// lies within `n_act` positions clockwise of `ptr`.  The layout must wire
// cell j to th[j]; the rotation is entirely in this logic.
//
//   stb   : convert strobe, one sample per pulse (may be held high)
//   valid : registered, high for one cycle after a strobe; `th`/`b` are the
//           sample latched on that edge and are stable while valid is high
//   ptr   : current DWA pointer (0..14), advanced on the strobe for the *next*
//           sample.  `th`/`b` correspond to the pre-advance pointer.
//
// The pointer is advanced by the unary cell count of the incoming sample,
// which is what makes 15 consecutive samples tile the 15 cells exactly once
// for n_act = 1 and n_act times each in general.  Both `th` and `b` are
// registered, so the analog switches never see the asynchronous code bus.
`timescale 1ns / 1ps
`default_nettype none

module dac_csteer_dig (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        stb,
    input  wire [7:0]  code,
    output reg  [14:0] th,
    output reg  [3:0]  b,
    output reg  [3:0]  ptr,
    output reg         valid,
    output wire [7:0]  code_q
);

    localparam N_UNARY = 15;

    reg [7:0] code_r;
    assign code_q = code_r;

    wire [3:0] n_act = code[7:4];          // unary cells in the incoming sample
    wire [4:0] ptr_sum = {1'b0, ptr} + {1'b0, n_act};
    // ptr < 15 and n_act <= 15, so ptr_sum <= 29 and one conditional subtract
    // is enough to reduce modulo 15.
    wire [3:0] ptr_next = (ptr_sum >= 5'd15) ? (ptr_sum[3:0] - 4'd15)
                                             : ptr_sum[3:0];

    // Rotated thermometer, d(j) = (j - ptr) mod 15, one cell per generate.
    wire [14:0] th_dec;
    genvar j;
    generate
        for (j = 0; j < N_UNARY; j = j + 1) begin : g_th
            wire [4:0] base = j;
            wire [4:0] diff = (base >= {1'b0, ptr})
                            ? (base - {1'b0, ptr})
                            : (base + 5'd15 - {1'b0, ptr});
            assign th_dec[j] = (diff < {1'b0, n_act});
        end
    endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            code_r <= 8'h00;
            th     <= 15'b0;
            b      <= 4'h0;
            ptr    <= 4'd0;
            valid  <= 1'b0;
        end else begin
            valid <= stb;
            if (stb) begin
                // Sample with the pointer that is active now, then advance it.
                code_r <= code;
                th     <= th_dec;
                b      <= code[3:0];
                ptr    <= ptr_next;
            end
        end
    end

endmodule

`default_nettype wire
