module top (
    input logic in_i,
    output logic out_o
);
    logic state;
    logic [1:0] child_o;
    assign state = in_i;
    child u_first(.in_i(in_i), .out_o(child_o[0]));
    child u_second(.in_i(in_i), .out_o(child_o[1]));
    assign out_o = child_o[0] ^ state;
endmodule
