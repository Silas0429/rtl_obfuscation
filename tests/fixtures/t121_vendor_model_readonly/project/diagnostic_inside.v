`ifndef YOSYS
  `protect // empty vendor protection marker
  `endprotect
	`protect
	`endprotect // second ordered pair
  `suppress_faults
  `enable_portfaults // vendor fault mode
`endif

module t121_diagnostic_cell (
    input  wire data_i,
    output wire data_o
);
    wire diagnostic_signal;
    assign diagnostic_signal = data_i;
    assign data_o = diagnostic_signal;
`ifndef YOSYS
    specify
        ifnone (posedge data_i => (data_o+:1'b1)) = 0;
    endspecify
`endif
endmodule

`ifndef YOSYS
  `disable_portfaults
  `nosuppress_faults
`endif
