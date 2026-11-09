// SPDX-License-Identifier: Apache-2.0
//
// Digital half of the binary CDAC leaf (8 bit, differential).
//
// The analog core is 2 x (2^N-1 switched unit capacitors + 1 dummy) with two
// transmission gates per bit: one bottom-plate switch to VREFH, one to VREFL.
// Three things must not be left to the analog side:
//
//   1. a code change is break-before-make: b and bb are both zero for at least
//      one full clock before the new code is applied, so VREFH and VREFL are
//      never shorted through a bit node while the switches move;
//   2. the sampling switch and the top-plate precharge are released before any
//      bit switch closes, and the bit switches are released before sampling
//      starts (sample -> break -> drive, drive -> break -> sample);
//   3. the analog gates never see the asynchronous code bus.
//
//   smp   : level, 1 = sampling phase (input switch + top-plate reset on)
//   stb   : pulse, apply `code` during the drive phase (break first)
//   code  : asynchronous code bus, latched while sampling and on stb
//
//   b[k]  : bottom plate to VREFH   (gate drive, active high)
//   bb[k] : bottom plate to VREFL   (complementary gate drive)
//   valid : 1 while the latched code is applied
//
// In the drive phase b = code_q and bb = ~code_q, so exactly one gate per bit
// is closed; b & bb is zero in every state, including the break cycle.
`timescale 1ns / 1ps
`default_nettype none

module dac_cdac_dig #(
    parameter N = 8
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         smp,
    input  wire         stb,
    input  wire [N-1:0] code,
    output reg  [N-1:0] b,
    output reg  [N-1:0] bb,
    output reg          smp_o,
    output reg          pre,
    output reg          valid,
    output reg  [N-1:0] code_q
);

    localparam S_SAMPLE = 2'd0;
    localparam S_BREAK  = 2'd1;
    localparam S_DRIVE  = 2'd2;

    reg [1:0] state;
    reg       started;        // set once the first sampling phase is entered
    reg       brk_to_sample;  // where to go after the break cycle

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state         <= S_SAMPLE;
            started       <= 1'b0;
            brk_to_sample <= 1'b0;
            b             <= {N{1'b0}};
            bb            <= {N{1'b0}};
            smp_o         <= 1'b0;
            pre           <= 1'b0;
            valid         <= 1'b0;
            code_q        <= {N{1'b0}};
        end else begin
            case (state)
                S_SAMPLE: begin
                    // all bit switches open
                    b      <= {N{1'b0}};
                    bb     <= {N{1'b0}};
                    valid  <= 1'b0;
                    code_q <= code;
                    if (smp) begin
                        started <= 1'b1;
                        smp_o   <= 1'b1;
                        pre     <= 1'b1;
                    end else begin
                        smp_o <= 1'b0;
                        pre   <= 1'b0;
                        if (started) begin
                            // release sampling, then break, then drive
                            brk_to_sample <= 1'b0;
                            state         <= S_BREAK;
                        end
                    end
                end

                S_BREAK: begin
                    // one full cycle with every switch open
                    b     <= {N{1'b0}};
                    bb    <= {N{1'b0}};
                    smp_o <= 1'b0;
                    pre   <= 1'b0;
                    valid <= 1'b0;
                    if (brk_to_sample) begin
                        state <= S_SAMPLE;
                    end else begin
                        // the off cycle has elapsed: apply the latched code
                        b     <= code_q;
                        bb    <= ~code_q;
                        valid <= 1'b1;
                        state <= S_DRIVE;
                    end
                end

                S_DRIVE: begin
                    b     <= code_q;
                    bb    <= ~code_q;
                    smp_o <= 1'b0;
                    pre   <= 1'b0;
                    valid <= 1'b1;
                    if (smp) begin
                        // stop driving, break, then start sampling
                        code_q        <= code;
                        b             <= {N{1'b0}};
                        bb            <= {N{1'b0}};
                        valid         <= 1'b0;
                        brk_to_sample <= 1'b1;
                        state         <= S_BREAK;
                    end else if (stb) begin
                        // new trial code: open everything for one cycle
                        code_q        <= code;
                        b             <= {N{1'b0}};
                        bb            <= {N{1'b0}};
                        valid         <= 1'b0;
                        brk_to_sample <= 1'b0;
                        state         <= S_BREAK;
                    end
                end

                default: begin
                    state <= S_SAMPLE;
                    b     <= {N{1'b0}};
                    bb    <= {N{1'b0}};
                end
            endcase
        end
    end

endmodule

`default_nettype wire
