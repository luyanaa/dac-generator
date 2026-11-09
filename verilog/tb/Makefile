# Self-checking regression for the delta-sigma audio DAC and the R-2R
# digital front end.
#
#   make            # compile + run both testbenches
#   make dac_r2r_dig# compile + run the R-2R digital testbench
#   make lint       # Verilator lint of the RTL
#   make wave       # regenerate and open the VCD (needs a viewer)
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

.PHONY: all run lint clean wave dac_r2r_dig

all: run dac_r2r_dig

$(OUT): $(TB) $(SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s audiodac_tb $(TB) $(SRCS)

run: $(OUT)
	$(VVP) $(OUT)

$(R2R_OUT): $(R2R_TB) $(R2R_SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s dac_r2r_dig_tb $(R2R_TB) $(R2R_SRCS)

dac_r2r_dig: $(R2R_OUT)
	$(VVP) $(R2R_OUT)

lint: $(SRCS) $(R2R_SRCS)
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module audiodac \
		-I$(RTL) $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v \
		$(RTL)/audiodac_fifo.v $(RTL)/audiodac_sinegen.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_r2r_dig \
		-I$(RTL) $(RTL)/dac_r2r_dig.v

wave: $(OUT)
	$(VVP) $(OUT)
	@echo "wrote audiodac_tb.vcd"

clean:
	rm -f $(OUT) audiodac_tb.vcd $(R2R_OUT)
