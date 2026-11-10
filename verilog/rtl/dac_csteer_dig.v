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
// The switch drive is also generated here, because the analog core exposes one
// gate pad per steering switch and the complementary phase must not be left to
// the wrapper: `swa_*` is the selected cell's high side and `swb_*` its
// complement, both registered with `th`/`b` so a switch pair never sees an
// asynchronous code.  The names match the analog macro's pads:
//
//   swa_u[j]      -> swa_u<j>        swb_u[j]      -> swb_u<j>      (j 0..14)
//   swa_b1_0      -> swa_b1_0        swb_b1_0      -> swb_b1_0
//   swa_b2[j]     -> swa_b2_<j>      swb_b2[j]     -> swb_b2_<j>    (j 0..1)
//   swa_b4[j]     -> swa_b4_<j>      swb_b4[j]     -> swb_b4_<j>    (j 0..3)
//   swa_b8[j]     -> swa_b8_<j>      swb_b8[j]     -> swb_b8_<j>    (j 0..7)
//
// A binary bit drives all of its cells from one register bit, so the weight is
// the number of cells on that net (1/2/4/8), not a separate decode.
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
    output wire [7:0]  code_q,
    output wire [14:0] swa_u,
    output wire [14:0] swb_u,
    output wire        swa_b1_0,
    output wire        swb_b1_0,
    output wire [1:0]  swa_b2,
    output wire [1:0]  swb_b2,
    output wire [3:0]  swa_b4,
    output wire [3:0]  swb_b4,
    output wire [7:0]  swa_b8,
    output wire [7:0]  swb_b8
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

    // Steering-switch drive.  `th` is already indexed by physical cell, so the
    // unary phase is a straight fan-out; each binary bit feeds all its cells.
    assign swa_u    = th;
    assign swb_u    = ~th;
    assign swa_b1_0 = b[0];
    assign swb_b1_0 = ~b[0];
    assign swa_b2   = {2{b[1]}};
    assign swb_b2   = ~{2{b[1]}};
    assign swa_b4   = {4{b[2]}};
    assign swb_b4   = ~{4{b[2]}};
    assign swa_b8   = {8{b[3]}};
    assign swb_b8   = ~{8{b[3]}};

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
