module t104_child (
    input logic clk,
    `T104_PORT_DECL(child_in),
    output logic child_out
);
    logic clean_child;

    assign clean_child = `T104_SIG_REF(child_in);
    assign child_out = clean_child;
endmodule
