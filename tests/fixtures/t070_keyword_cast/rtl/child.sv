module t070_keyword_cast_child (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    typedef logic [7:0] byte_t;

    byte_t typed_value;
    byte_t signed_value;
    byte_t unsigned_value;

    always_comb begin
        typed_value = byte_t'(data_i);
        signed_value = signed'(typed_value);
        unsigned_value = unsigned'(typed_value);
        data_o = typed_value ^ signed_value ^ unsigned_value;
    end
endmodule
