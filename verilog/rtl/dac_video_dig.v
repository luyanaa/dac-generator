// SPDX-License-Identifier: Apache-2.0
//
// Digital half of the 8-bit 25 MS/s video current-steering DAC leaf (P5).
//
// The analog core is 255 identical unit current cells grouped 1/2/4/.../128
// and decoded straight from the binary code.  There is no DEM here on
// purpose: P3 already owns segmented + DWA.  This leaf asks whether a plain
// binary decoder is viable at video rate, and the answer has two parts that
// this module has to respect:
//
//   1. every bit slice must launch on the same clock edge, from one register,
//      so the module does not add decoder skew to the binary carry.  The
//      residual skew is layout launch/clock-tree work, not logic.
//   2. a binary carry is a large simultaneous switch (127 LSB off, 128 LSB
//      on at mid-code).  Measured on the pre-layout model, 25 ps of bit
//      skew turns that into a 50 LSB transient that needs ~0.8 ns to settle
//      back to 0.5 LSB.  The system must therefore not sample, and must not
//      start the next code, inside that window.
//
// `dout` is one bit per *physical* cell, not per code bit: the analog macro is
// a row of 255 unit cells and each cell exposes exactly one switch gate, so
// the array is driven by 255 wires and the binary weight is the number of
// cells on each net.  Cell j belongs to the smallest k with j < 2^(k+1) - 1:
//
//   bit 0 -> cell   0            (1 cell)      bit 4 -> cells  15..30   (16)
//   bit 1 -> cells  1..2         (2)           bit 5 -> cells  31..62   (32)
//   bit 2 -> cells  3..6         (4)           bit 6 -> cells  63..126  (64)
//   bit 3 -> cells  7..14        (8)           bit 7 -> cells 127..254 (128)
//
// Every bit of dout comes from the same launch edge and the same latched
// code, so the bus itself adds no skew between bit slices.
//
// `ready` is that contract: it goes low on a launch and stays low for
// SETTLE_CYCLES clock cycles (counting the launch cycle), then goes high
// again.  `stb` is ignored while `ready` is low.  At 25 MS/s a 40 ns period
// is 100x the measured settling, so SETTLE_CYCLES = 4 (40 ns at 100 MHz,
// 160 ns at the 25 MS/s sample rate) is a guard band, not a speed limit.
//
//   stb   : launch request, one cycle, ignored while !ready
//   code  : asynchronous input bus, only sampled on an accepted stb
//   dout  : registered analog switch bus, stable between launches
//   valid : one-cycle pulse on an accepted launch
//   ready : high when the last code has had its settle window
`timescale 1ns / 1ps
`default_nettype none

module dac_video_dig #(
    parameter integer SETTLE_CYCLES = 4
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       stb,
    input  wire [7:0]   code,
    output reg  [254:0] dout,
    output reg        valid,
    output reg        ready
);

    // Counter wide enough for SETTLE_CYCLES; the +1 keeps SETTLE_CYCLES=0
    // (pass-through) legal without a zero-width vector.
    localparam integer CW = (SETTLE_CYCLES <= 1) ? 1 : $clog2(SETTLE_CYCLES + 1);

    reg [CW-1:0] timer;

    wire launch = stb & ready;

    // Combinational expansion of the code bus; dout registers it on a launch,
    // so the switch bus is still a single flop stage behind `stb`.
    wire [254:0] dout_dec;
    genvar gk, gi;
    generate
        for (gk = 0; gk < 8; gk = gk + 1) begin : g_bit
            for (gi = 0; gi < (1 << gk); gi = gi + 1) begin : g_cell
                assign dout_dec[(1 << gk) - 1 + gi] = code[gk];
            end
        end
    endgenerate

    always @(posedge clk) begin
        if (!rst_n) begin
            dout  <= {255{1'b0}};
            valid <= 1'b0;
            ready <= 1'b1;
            timer <= {CW{1'b0}};
        end else begin
            valid <= 1'b0;
            if (launch) begin
                dout  <= dout_dec;
                valid <= 1'b1;
                timer <= {CW{1'b0}};
                ready <= (SETTLE_CYCLES == 0);
            end else if (!ready) begin
                if (timer == CW'(SETTLE_CYCLES - 1)) begin
                    ready <= 1'b1;
                    timer <= {CW{1'b0}};
                end else begin
                    timer <= timer + 1'b1;
                end
            end
        end
    end

endmodule
`default_nettype wire
