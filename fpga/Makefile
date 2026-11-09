# FPGA synthesis / place-and-route for the digital DAC backends.
#
#   make                 # audiodac on iCE40 UP5K + ECP5, pwmdac/dac_wrap on ECP5
#   make audiodac-ice40-bit
#   make clean
#
# Toolchain: OSS CAD Suite (yosys + nextpnr). Override the location with
#   make OSS_CAD_SUITE=/path/to/oss-cad-suite
#
# These targets are a bring-up / resource smoke test, not a signoff flow.

OSS_CAD_SUITE ?= /opt/oss-cad-suite
YOSYS         ?= $(OSS_CAD_SUITE)/bin/yosys
NEXTPNR_ICE40 ?= $(OSS_CAD_SUITE)/bin/nextpnr-ice40
NEXTPNR_ECP5  ?= $(OSS_CAD_SUITE)/bin/nextpnr-ecp5
ICEPACK       ?= $(OSS_CAD_SUITE)/bin/icepack
ECPPACK       ?= $(OSS_CAD_SUITE)/bin/ecppack

RTL   := ../verilog/rtl
BUILD := build
FREQ     ?= 20
# The corrected 2nd-order CIFF loop is deeper than the old 2-bit stage, so
# 18 MHz no longer closes on UP5K; ~14.7 MHz is the measured limit.  OSR=256
# at 48 kHz needs 12.288 MHz, so 14 MHz still covers the intended use.
FREQ_ICE ?= 14

ICE_DEV  := --up5k --package sg48
ECP5_DEV := --25k --package CABGA256

RTL_AUDIO := $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v $(RTL)/audiodac_fifo.v $(RTL)/audiodac_sinegen.v
RTL_PWM   := $(RTL)/pwmdac.v $(RTL)/pwmdac_pwm.v $(RTL)/audiodac_fifo.v
RTL_WRAP  := $(RTL)/dac_wrap.v $(RTL)/pwmdac.v $(RTL)/pwmdac_pwm.v \
             $(RTL)/audiodac.v $(RTL)/audiodac_dsmod.v $(RTL)/audiodac_fifo.v \
             $(RTL)/audiodac_sinegen.v

all: audiodac-ice40 audiodac-ecp5 pwmdac-ecp5 dac_wrap-ecp5

$(BUILD):
	mkdir -p $(BUILD)

# ---------------------------------------------------------------- audiodac
# Delta-sigma backend, standalone top. 39 I/O -> exactly the 39 SB_IO of the
# iCE40 UP5K sg48 package.
$(BUILD)/audiodac_ice40.json: $(RTL_AUDIO) | $(BUILD)
	$(YOSYS) -p "read_verilog $(RTL)/audiodac.v; synth_ice40 -top audiodac -json $@"

$(BUILD)/audiodac_ice40.asc: $(BUILD)/audiodac_ice40.json
	$(NEXTPNR_ICE40) $(ICE_DEV) --json $< --pcf-allow-unconstrained \
		--freq $(FREQ_ICE) --asc $@ --report $(BUILD)/audiodac_ice40.pnr.json

$(BUILD)/audiodac_ice40.bin: $(BUILD)/audiodac_ice40.asc
	$(ICEPACK) $< $@

audiodac-ice40: $(BUILD)/audiodac_ice40.asc
audiodac-ice40-bit: $(BUILD)/audiodac_ice40.bin

$(BUILD)/audiodac_ecp5.json: $(RTL_AUDIO) | $(BUILD)
	$(YOSYS) -p "read_verilog $(RTL)/audiodac.v; synth_ecp5 -top audiodac -json $@"

$(BUILD)/audiodac_ecp5.config: $(BUILD)/audiodac_ecp5.json
	$(NEXTPNR_ECP5) $(ECP5_DEV) --json $< --lpf-allow-unconstrained \
		--freq $(FREQ) --textcfg $@ --report $(BUILD)/audiodac_ecp5.pnr.json

$(BUILD)/audiodac_ecp5.bit: $(BUILD)/audiodac_ecp5.config
	$(ECPPACK) $< $@

audiodac-ecp5: $(BUILD)/audiodac_ecp5.config
audiodac-ecp5-bit: $(BUILD)/audiodac_ecp5.bit

# ------------------------------------------------------------------ pwmdac
# PWM backend. 41 I/O, so it does not fit the 39-pin UP5K sg48; use ECP5 or a
# larger package / trim the two test ports on iCE40.
$(BUILD)/pwmdac_ecp5.json: $(RTL_PWM) | $(BUILD)
	$(YOSYS) -p "read_verilog $(RTL)/pwmdac.v; synth_ecp5 -top pwmdac -json $@"

$(BUILD)/pwmdac_ecp5.config: $(BUILD)/pwmdac_ecp5.json
	$(NEXTPNR_ECP5) $(ECP5_DEV) --json $< --lpf-allow-unconstrained \
		--freq $(FREQ) --textcfg $@ --report $(BUILD)/pwmdac_ecp5.pnr.json

$(BUILD)/pwmdac_ecp5.bit: $(BUILD)/pwmdac_ecp5.config
	$(ECPPACK) $< $@

pwmdac-ecp5: $(BUILD)/pwmdac_ecp5.config
pwmdac-ecp5-bit: $(BUILD)/pwmdac_ecp5.bit

# ---------------------------------------------------------------- dac_wrap
# Backend-selectable wrapper, delta-sigma flavour (DAC_KIND=1). The port list
# is the union of both backends (55 I/O), so ECP5 only.
$(BUILD)/dac_wrap_ecp5.json: $(RTL_WRAP) | $(BUILD)
	$(YOSYS) -p "read_verilog $(RTL)/dac_wrap.v; chparam -set DAC_KIND 1 dac_wrap; synth_ecp5 -top dac_wrap -json $@"

$(BUILD)/dac_wrap_ecp5.config: $(BUILD)/dac_wrap_ecp5.json
	$(NEXTPNR_ECP5) $(ECP5_DEV) --json $< --lpf-allow-unconstrained \
		--freq $(FREQ) --textcfg $@ --report $(BUILD)/dac_wrap_ecp5.pnr.json

$(BUILD)/dac_wrap_ecp5.bit: $(BUILD)/dac_wrap_ecp5.config
	$(ECPPACK) $< $@

dac_wrap-ecp5: $(BUILD)/dac_wrap_ecp5.config
dac_wrap-ecp5-bit: $(BUILD)/dac_wrap_ecp5.bit

clean:
	rm -rf $(BUILD)

.PHONY: all clean audiodac-ice40 audiodac-ice40-bit audiodac-ecp5 \
        audiodac-ecp5-bit pwmdac-ecp5 pwmdac-ecp5-bit dac_wrap-ecp5 \
        dac_wrap-ecp5-bit
