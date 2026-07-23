`define DECLARE_SIGNAL(name) logic name

module macro_declaration;
    `DECLARE_SIGNAL(macro_state);
    assign macro_state = 1'b0;
endmodule
