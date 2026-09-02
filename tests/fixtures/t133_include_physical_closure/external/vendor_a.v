module t133_vendor_a (
    input  logic [`T133_WIDTH-1:0] in_data,
    output logic [`T133_WIDTH-1:0] out_data
);
    `include "vendor_function.inc"
    assign out_data = vendor_mix(in_data);
endmodule
