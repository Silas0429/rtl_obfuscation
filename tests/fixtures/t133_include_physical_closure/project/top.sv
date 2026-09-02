module t133_top (
    input  logic [`T133_WIDTH-1:0] source_data,
    output logic [`T133_WIDTH-1:0] result_data
);
    logic [`T133_WIDTH-1:0] first_stage;
    logic [`T133_WIDTH-1:0] second_stage;

    t133_vendor_a u_vendor_a (
        .in_data(source_data),
        .out_data(first_stage)
    );
    t133_vendor_b u_vendor_b (
        .in_data(first_stage),
        .out_data(second_stage)
    );

    assign result_data = second_stage ^ `T133_WIDTH'h5;
endmodule
