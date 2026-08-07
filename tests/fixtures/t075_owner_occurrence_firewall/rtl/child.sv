module t075_child (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_state;

    assign child_state = data_i ^ 8'h3c;
    assign data_o = child_state;
endmodule
