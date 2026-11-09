# Self-checking regression for the delta-sigma audio DAC and the analog-leaf
# digital front ends.
#
#   make              # compile + run every testbench
#   make dac_r2r_dig  # R-2R digital testbench
#   make dac_string_dig # resistor-string digital testbench
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

.PHONY: all run lint clean wave dac_r2r_dig dac_string_dig

all: run dac_r2r_dig dac_string_dig

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

lint: $(SRCS) $(R2R_SRCS) $(STR_SRCS)
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module audiodac \
		-I$(RTL) $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v \
		$(RTL)/audiodac_fifo.v $(RTL)/audiodac_sinegen.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_r2r_dig \
		-I$(RTL) $(RTL)/dac_r2r_dig.v
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module dac_string_dig \
		-I$(RTL) $(RTL)/dac_string_dig.v

wave: $(OUT)
	$(VVP) $(OUT)
	@echo "wrote audiodac_tb.vcd"

clean:
	rm -f $(OUT) audiodac_tb.vcd $(R2R_OUT) $(STR_OUT)
