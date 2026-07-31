module t069_sized_cast_child #(
    parameter int WIDTH = 4,
    parameter int RESET_VALUE = WIDTH'(0)
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    localparam int LOCAL_WIDTH = WIDTH;
    logic [WIDTH-1:0] cast_value;

    always_comb begin
        cast_value = LOCAL_WIDTH'(data_i);
    end

    assign data_o = cast_value ^ WIDTH'(RESET_VALUE);
endmodule
