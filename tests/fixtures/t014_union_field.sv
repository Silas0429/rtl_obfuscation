module t014_union_field (
    input  logic [31:0] data_in,
    output logic [31:0] data_out
);
    typedef union packed {
        logic [31:0] word;
        logic [31:0] reversed;
    } data_t;

    data_t stored_data;
    data_t temp_data;

    always_comb begin
        temp_data.word = data_in;
        stored_data = temp_data;
        data_out = stored_data.reversed;
    end
endmodule
