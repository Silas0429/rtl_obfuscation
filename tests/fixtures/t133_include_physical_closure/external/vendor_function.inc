function automatic logic [`T133_WIDTH-1:0] vendor_mix(
    input logic [`T133_WIDTH-1:0] value
);
    logic [`T133_WIDTH-1:0] scratch;
    begin
        scratch = value ^ `T133_WIDTH'h3;
        vendor_mix = scratch;
    end
endfunction
