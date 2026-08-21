module t100_macro_owner #(
    parameter int WIDTH = 8
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    logic [WIDTH-1:0] cell_data;

    `define T100_MAKE_CELL(CELL_NAME, DATA_W, DEPTH, BE_W, CELL_OUT) \
        if ((DEPTH) == 4 && (BE_W) == 1) begin : g_macro_cell \
            logic [(DATA_W)-1:0] generated_data; \
            assign generated_data = data_i; \
            t100_cell #(.WIDTH(DATA_W)) CELL_NAME ( \
                .data_i(generated_data), \
                .data_o(CELL_OUT) \
            ); \
        end

    generate
        `T100_MAKE_CELL(u_macro_cell, WIDTH, 4, 1, cell_data)
        else begin : g_fallback
            assign cell_data = data_i;
        end
    endgenerate

    assign data_o = cell_data;
endmodule
