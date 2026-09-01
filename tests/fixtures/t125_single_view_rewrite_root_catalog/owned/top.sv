module t125_top (
    input logic in_i,
    output logic out_o
);
    logic child_o;
    t125_child u_child(.in_i(in_i), .out_o(child_o));
    assign out_o = child_o;
endmodule
