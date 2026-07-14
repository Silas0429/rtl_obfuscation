module t014_struct_field (
    input  logic [7:0] data_in,
    output logic [7:0] data_out
);
    typedef struct packed {
        logic [3:0] low_nibble;
        logic [3:0] high_nibble;
    } header_t;

    header_t stored_header;
    header_t temp_header;

    always_comb begin
        temp_header.low_nibble  = data_in[3:0];
        temp_header.high_nibble = data_in[7:4];
        stored_header = temp_header;
        data_out = {stored_header.high_nibble, stored_header.low_nibble};
    end
endmodule
