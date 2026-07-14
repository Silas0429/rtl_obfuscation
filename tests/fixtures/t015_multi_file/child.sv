module t015_child (
    input  logic [7:0] data_in,
    output logic [7:0] data_out
);
    typedef logic [7:0] byte_t;

    byte_t stored_value;
    byte_t temp_value;

    always_comb begin
        temp_value = data_in;
        stored_value = temp_value;
        data_out = stored_value;
    end
endmodule
