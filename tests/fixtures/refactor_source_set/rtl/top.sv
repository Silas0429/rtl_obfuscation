module top (
    input logic [7:0] in_data,
    output logic [7:0] out_data
);
    child u_child(.in_data(in_data), .out_data(out_data));
endmodule
