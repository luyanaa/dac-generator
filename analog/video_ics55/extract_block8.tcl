drc off
gds read build/video_ics55_8_pex.gds
load dac_video_ana
select top cell
extract do local
extract all
ext2spice cthresh 0
ext2spice -o build/block8_pex2.spice
quit -noprompt
