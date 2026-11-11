// SPDX-License-Identifier: Apache-2.0
//
// Digital half of the video current-steering DAC leaf.
//
// The analog core is a row of 255 identical unit current cells.  Each cell
// exposes one switch gate; the array is driven by 255 wires and the code is
// expanded onto them.  Two encodings are supported because the two PDK
// leaves have different mismatch limits:
//
//   ENCODING = 0 (binary)       RESOLUTION bits, 2^RESOLUTION-1 cells used
//   ENCODING = 1 (thermometer)  RESOLUTION bits, cells 0..code-1 on
//
// The sky130 5 V cell is mismatch-limited (sigma 5.5 %/cell), so its leaf is
// specified as RESOLUTION=7 / ENCODING=1 (127 of the 255 cells; the rest are
// held off).  GF180 and IHP use RESOLUTION=8 / ENCODING=0.
//
//   1. every slice launches on the same clock edge, from one register, so the
//      module adds no decoder skew to a carry;
//   2. a carry is a large simultaneous switch; the system must not sample and
//      must not start the next code inside the settling window.
//
// `ready` is that contract: it goes low on a launch and stays low for
// SETTLE_CYCLES clock cycles (counting the launch cycle), then goes high
// again.  `stb` is ignored while `ready` is low.  The sustained accept rate is
// f_clk / (SETTLE_CYCLES + 1); the default SETTLE_CYCLES=3 gives 25 MS/s at
// 100 MHz, which is the video leaf's sample rate.  A larger value is a guard
// band, not a speed requirement.
//
//   stb   : launch request, one cycle, ignored while !ready
//   code  : asynchronous input bus, only sampled on an accepted stb
//   dout  : registered analog switch bus, stable between launches
//   dout_n: complementary switch bus (same register, inverted)
//   valid : one-cycle pulse on an accepted launch
//   ready : high when the last code has had its settle window
`timescale 1ns / 1ps
`default_nettype none

module dac_video_dig #(
    parameter integer RESOLUTION = 8,
    parameter integer ENCODING = 0,       // 0 = binary, 1 = thermometer
    parameter integer SETTLE_CYCLES = 3
) (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    stb,
    input  wire [RESOLUTION-1:0]   code,
    output reg  [254:0]            dout,
    output wire [254:0]            dout_n,
    output reg                     valid,
    output reg                     ready
);

    // Counter wide enough for SETTLE_CYCLES; the +1 keeps SETTLE_CYCLES=0
    // (pass-through) legal without a zero-width vector.
    localparam integer CW = (SETTLE_CYCLES <= 1) ? 1 : $clog2(SETTLE_CYCLES + 1);
    localparam [CW-1:0] TIMER_LAST = SETTLE_CYCLES - 1;

    reg [CW-1:0] timer;

    wire launch = stb & ready;

    // Expansion onto the 255 physical cells.  Binary: cell j belongs to the
    // smallest k with j < 2^(k+1) - 1.  Thermometer: cells 0..code-1 on.
    // Cells beyond 2^RESOLUTION-1 are held off in both encodings.
    wire [254:0] dout_dec;
    genvar gk, gi, gj;
    generate
        if (ENCODING == 0) begin : g_bin
            for (gk = 0; gk < RESOLUTION; gk = gk + 1) begin : g_bit
                for (gi = 0; gi < (1 << gk); gi = gi + 1) begin : g_cell
                    assign dout_dec[(1 << gk) - 1 + gi] = code[gk];
                end
            end
            for (gj = (1 << RESOLUTION) - 1; gj < 255; gj = gj + 1)
                begin : g_off
                    assign dout_dec[gj] = 1'b0;
                end
        end else begin : g_th
            for (gj = 0; gj < 255; gj = gj + 1) begin : g_cell
                assign dout_dec[gj] = (gj < (1 << RESOLUTION) - 1)
                    ? (gj < code) : 1'b0;
            end
        end
    endgenerate

    assign dout_n = ~dout;

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
                if (timer == TIMER_LAST) begin
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
