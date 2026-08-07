module t076_labeled_child (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_state;

    assign child_state = data_i ^ 8'h5a;
    assign data_o = child_state;
endmodule : t076_labeled_child
