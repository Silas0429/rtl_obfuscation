module t117_top (
    input  logic in_a,
    input  logic in_b,
    output logic out_y
);
    logic library_value;

    t117_library_cell library_instance (
        .in_a(in_a),
        .in_b(in_b),
        .out_y(library_value)
    );

    assign out_y = library_value;
endmodule
