module top (
    input logic in_i,
    output logic out_o
);
    logic [1:0] child_o;
    genvar index;
    generate
        for (index = 0; index < 2; index++) begin : child_gen
            child u_child(.in_i(in_i), .out_o(child_o[index]));
        end
    endgenerate
    assign out_o = child_o[0] ^ child_o[1];
endmodule
