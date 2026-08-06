# xschem_lib_sg13g2_stdcell_hv.tcl -- register the thick-oxide (3.3 V)
# standard cell library with xschem.
#
# Source this AFTER the PDK xschemrc, alongside the other shared cell
# libraries:
#
#     source $env(PDK_ROOT)/$env(PDK)/libs.tech/xschem/xschemrc
#     source /foss/designs/sg13g2_stdcell_hv/xschem_lib_sg13g2_stdcell_hv.tcl
#
# The symbols are copies of the thin-oxide sg13g2_stdcell symbols: same drawn
# geometry, same pin names, same pin order. Two things differ.
#
#   * template prefix is sg13g2_hv_, so an instance netlists to
#     sg13g2_hv_<cell> and the thin- and thick-oxide libraries can appear in
#     one netlist without a name clash.
#
#   * the symbols carry type=subcircuit and resolve their schematic through
#     $::SG13G2_HV_SCH, set below. The thin-oxide symbols instead go through
#     the PDK's hierarchy_config proc, which is hard-wired to the
#     sg13g2_stdcell schematic directory and has no thick-oxide view.
#
# Existing path entries and missing directories are skipped, so double-
# sourcing is safe.

set SG13G2_HV_ROOT [file normalize [file dirname [info script]]]

# Where the symbols look for their schematics. Must be set before any
# thick-oxide symbol is loaded.
set ::SG13G2_HV_SCH [file join $SG13G2_HV_ROOT sch xschem]

# The cell gallery, for rc files that want to open it at startup.
set ::SG13G2_HV_GALLERY [file join $::SG13G2_HV_SCH sg13g2_hv_stdcells.sch]

if {![info exists XSCHEM_LIBRARY_PATH]} { set XSCHEM_LIBRARY_PATH {} }

foreach __d [list \
    [file join $SG13G2_HV_ROOT sym xschem] \
    [file join $SG13G2_HV_ROOT sch xschem] \
] {
    if {[file isdirectory $__d]
        && [lsearch -exact [split $XSCHEM_LIBRARY_PATH :] $__d] < 0} {
        append XSCHEM_LIBRARY_PATH :$__d
    }
}
unset -nocomplain __d
