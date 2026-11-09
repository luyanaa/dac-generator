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
    input  wire [7:0] code,
    output reg  [7:0] dout,
    output reg        valid,
    output reg        ready
);

    // Counter wide enough for SETTLE_CYCLES; the +1 keeps SETTLE_CYCLES=0
    // (pass-through) legal without a zero-width vector.
    localparam integer CW = (SETTLE_CYCLES <= 1) ? 1 : $clog2(SETTLE_CYCLES + 1);

    reg [CW-1:0] timer;

    wire launch = stb & ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            dout  <= 8'd0;
            valid <= 1'b0;
            ready <= 1'b1;
            timer <= {CW{1'b0}};
        end else begin
            valid <= 1'b0;
            if (launch) begin
                dout  <= code;
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
