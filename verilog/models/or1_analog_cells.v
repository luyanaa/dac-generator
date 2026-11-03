// SPDX-License-Identifier: Apache-2.0
// Black-box Verilog model of sky130_fd_sc_hd__einvp_1 for non-sky130 PDKs.
//
// tempsense_vdac_cell.v directly instantiates the sky130 enable-inverter
// `sky130_fd_sc_hd__einvp_1` (tri-state inverter: Z = ~A when TE=1, Hi-Z when
// TE=0). On sky130 the real cell verilog is read as a black-box model via
// SYNTH_READ_BLACKBOX_LIB, the instances are preserved (RSZ_DONT_TOUCH_RX),
// and the LEF/GDS comes from the PDK at merge time.
//
// On other PDKs there is no einvp cell; this model lets the netlist
// elaborate so the rest of the design can be hardened. The vdac analog
// output will NOT be functional in silicon — a per-PDK equivalent cell
// (or a custom layout) is required for a real tapeout.
//
// `celldefine
/// sta-blackbox
/// sta-blackbox
/// sta-blackbox` + `blackbox` makes yosys treat it as a black-box cell.
`celldefine
/// sta-blackbox
/// sta-blackbox
(* blackbox *)
module sky130_fd_sc_hd__einvp_1 (
    Z   ,
    A   ,
    TE  ,
    VPWR,
    VGND,
    VPB ,
    VNB
);
    output wire Z   ;
    input  wire A   ;
    input  wire TE  ;
    input  wire VPWR;
    input  wire VGND;
    input  wire VPB ;
    input  wire VNB ;
endmodule
`endcelldefine

`celldefine
/// sta-blackbox
(* blackbox *)
module sky130_fd_sc_hd__inv_4 (Y, A, VPWR, VGND, VPB, VNB);
    output wire Y   ;
    input  wire A   ;
    input  wire VPWR;
    input  wire VGND;
    input  wire VPB ;
    input  wire VNB ;
endmodule
`endcelldefine

`celldefine
/// sta-blackbox
(* blackbox *)
module sky130_fd_sc_hd__inv_12 (Y, A, VPWR, VGND, VPB, VNB);
    output wire Y   ;
    input  wire A   ;
    input  wire VPWR;
    input  wire VGND;
    input  wire VPB ;
    input  wire VNB ;
endmodule
`endcelldefine
`default_nettype wire
