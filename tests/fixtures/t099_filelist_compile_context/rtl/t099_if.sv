`ifdef YOSYS
module t099_if_yosys_only;
endmodule
`else
interface t099_if;
    logic payload;
endinterface
`endif
