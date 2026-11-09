# Self-checking regression for the delta-sigma audio DAC and the analog-leaf
# digital front ends.
#
#   make              # compile + run every testbench
#   make dac_r2r_dig  # R-2R digital testbench
#   make dac_string_dig # resistor-string digital testbench
#   make dac_csteer_dig # unit-current-steering digital testbench
#   make dac_cdac_dig   # binary-CDAC digital testbench
#   make dac_video_dig  # video current-steering digital testbench
#   make lint         # Verilator lint of the RTL
#   make wave         # regenerate and open the VCD (needs a viewer)
#   make clean

RTL    := ../rtl
IVERILOG ?= iverilog
VVP      ?= vvp
VERILATOR ?= verilator

SRCS  := $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v \
         $(RTL)/audiodac_fifo.v $(RTL)/audiodac_sinegen.v
TB    := audiodac_tb.v
OUT   := audiodac_tb.vvp

R2R_SRCS := $(RTL)/dac_r2r_dig.v
R2R_TB   := dac_r2r_dig_tb.v
R2R_OUT  := dac_r2r_dig_tb.vvp

STR_SRCS := $(RTL)/dac_string_dig.v
STR_TB   := dac_string_dig_tb.v
STR_OUT  := dac_string_dig_tb.vvp

CS_SRCS := $(RTL)/dac_csteer_dig.v
CS_TB   := dac_csteer_dig_tb.v
CS_OUT  := dac_csteer_dig_tb.vvp

CD_SRCS := $(RTL)/dac_cdac_dig.v
CD_TB   := dac_cdac_dig_tb.v
CD_OUT  := dac_cdac_dig_tb.vvp

VID_SRCS := $(RTL)/dac_video_dig.v
VID_TB   := dac_video_dig_tb.v
VID_OUT  := dac_video_dig_tb.vvp

.PHONY: all run lint clean wave dac_r2r_dig dac_string_dig dac_csteer_dig dac_cdac_dig dac_video_dig

all: run dac_r2r_dig dac_string_dig dac_csteer_dig dac_cdac_dig dac_video_dig

$(OUT): $(TB) $(SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s audiodac_tb $(TB) $(SRCS)

run: $(OUT)
	$(VVP) $(OUT)

$(R2R_OUT): $(R2R_TB) $(R2R_SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s dac_r2r_dig_tb $(R2R_TB) $(R2R_SRCS)

dac_r2r_dig: $(R2R_OUT)
	$(VVP) $(R2R_OUT)

$(STR_OUT): $(STR_TB) $(STR_SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s dac_string_dig_tb $(STR_TB) $(STR_SRCS)

dac_string_dig: $(STR_OUT)
	$(VVP) $(STR_OUT)

$(CS_OUT): $(CS_TB) $(CS_SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s dac_csteer_dig_tb $(CS_TB) $(CS_SRCS)

dac_csteer_dig: $(CS_OUT)
	$(VVP) $(CS_OUT)

$(CD_OUT): $(CD_TB) $(CD_SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s dac_cdac_dig_tb $(CD_TB) $(CD_SRCS)

dac_cdac_dig: $(CD_OUT)
	$(VVP) $(CD_OUT)

$(VID_OUT): $(VID_TB) $(VID_SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s dac_video_dig_tb $(VID_TB) $(VID_SRCS)

dac_video_dig: $(VID_OUT)
	$(VVP) $(VID_OUT)

lint: $(SRCS) $(R2R_SRCS) $(STR_SRCS) $(CS_SRCS) $(CD_SRCS) $(VID_SRCS)
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module audiodac \
		-I$(RTL) $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v \
		$(RTL)/audiodac_fifo.v $(RTL)/audiodac_sinegen.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_r2r_dig \
		-I$(RTL) $(RTL)/dac_r2r_dig.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_string_dig \
		-I$(RTL) $(RTL)/dac_string_dig.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_csteer_dig \
		-I$(RTL) $(RTL)/dac_csteer_dig.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_cdac_dig \
		-I$(RTL) $(RTL)/dac_cdac_dig.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_video_dig \
		-I$(RTL) $(RTL)/dac_video_dig.v

wave: $(OUT)
	$(VVP) $(OUT)
	@echo "wrote audiodac_tb.vcd"

clean:
	rm -f $(OUT) audiodac_tb.vcd $(R2R_OUT) $(STR_OUT) $(CS_OUT) $(CD_OUT) $(VID_OUT)
