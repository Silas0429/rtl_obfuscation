module t134_top (
    input  logic [`T134_WIDTH-1:0] source_data,
    output logic [`T134_WIDTH-1:0] result_data
);
    logic [`T134_WIDTH-1:0] first_stage;
    logic [`T134_WIDTH-1:0] second_stage;

    t134_vendor_a u_vendor_a (
        .in_data(source_data),
        .out_data(first_stage)
    );
    t134_vendor_b u_vendor_b (
        .in_data(first_stage),
        .out_data(second_stage)
    );

    assign result_data = second_stage ^ `T134_WIDTH'h5;
endmodule
