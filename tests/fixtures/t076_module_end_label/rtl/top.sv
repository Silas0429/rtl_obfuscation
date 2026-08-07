module t076_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_o;
    logic [7:0] sibling_o;

    t076_labeled_child u_child (
        .data_i(data_i),
        .data_o(child_o)
    );
    t076_plain_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = child_o ^ sibling_o;
endmodule : t076_top
