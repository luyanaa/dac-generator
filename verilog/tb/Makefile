# Self-checking regression for the delta-sigma audio DAC.
#
#   make          # compile + run the testbench
#   make lint     # Verilator lint of the RTL
#   make wave     # regenerate and open the VCD (needs a viewer)
#   make clean

RTL    := ../rtl
IVERILOG ?= iverilog
VVP      ?= vvp
VERILATOR ?= verilator

SRCS  := $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v \
         $(RTL)/audiodac_fifo.v $(RTL)/audiodac_sinegen.v
TB    := audiodac_tb.v
OUT   := audiodac_tb.vvp

.PHONY: all run lint clean wave

all: run

$(OUT): $(TB) $(SRCS)
	$(IVERILOG) -g2012 -Wall -I$(RTL) -o $@ -s audiodac_tb $(TB) $(SRCS)

run: $(OUT)
	$(VVP) $(OUT)

lint: $(SRCS)
	$(VERILATOR) --lint-only -Wall -Wno-fatal --top-module audiodac \
		-I$(RTL) $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v \
		$(RTL)/audiodac_fifo.v $(RTL)/audiodac_sinegen.v

wave: $(OUT)
	$(VVP) $(OUT)
	@echo "wrote audiodac_tb.vcd"

clean:
	rm -f $(OUT) audiodac_tb.vcd
