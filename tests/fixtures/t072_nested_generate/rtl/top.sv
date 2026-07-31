module t072_top (
    input  logic data_i,
    output logic data_o
);
    logic nested_o;
    logic same_o;
    logic other_o;

    t072_nested_owner u_nested (
        .data_i(data_i),
        .data_o(nested_o)
    );
    t072_same_file_sibling u_same (
        .data_i(data_i),
        .data_o(same_o)
    );
    t072_other_sibling u_other (
        .data_i(data_i),
        .data_o(other_o)
    );

    assign data_o = nested_o ^ same_o ^ other_o;
endmodule
