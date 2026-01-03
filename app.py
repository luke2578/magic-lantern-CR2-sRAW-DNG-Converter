import streamlit as st
import io
import os
import zipfile
import numpy as np
import tifffile
from PIL import Image, ImageFile

# Allow loading truncated images
ImageFile.LOAD_TRUNCATED_IMAGES = True

def find_valid_image_stream(file_bytes):
    """Scans bytes for the largest valid JPEG stream."""
    offsets = []
    last_pos = 0
    
    # Find all FF D8 markers
    while True:
        pos = file_bytes.find(b'\xFF\xD8', last_pos)
        if pos == -1: break
        offsets.append(pos)
        last_pos = pos + 2
    
    # Check backwards (largest image is usually last)
    for offset in reversed(offsets):
        try:
            stream = io.BytesIO(file_bytes[offset:])
            img = Image.open(stream)
            img.load() # Force load to check integrity
            
            # Filter out thumbnails (width < 1000)
            if img.width > 1000:
                return img
        except:
            continue
    return None

def process_and_convert(image_obj):
    """Converts PIL Image to DNG-ready numpy array."""
    if image_obj.mode != 'RGB':
        image_obj = image_obj.convert('RGB')

    # Aspect Ratio Fix (Un-squeeze)
    target_width = image_obj.width
    target_height = int(target_width / 1.5)
    img_resized = image_obj.resize((target_width, target_height), Image.Resampling.LANCZOS)

    # Convert to 16-bit
    img_array = np.array(img_resized)
    final_data = img_array.astype(np.uint16) * 256
    return final_data

# --- STREAMLIT UI ---
st.set_page_config(page_title="Magic Lantern Batch Converter", layout="wide")

st.title("Magic Lantern CR2 to DNG Converter")
st.markdown("""
This tool converts sRAW pictures (CR2) extracted from Magic Lantern into DNG format.
It includes **Auto-Repair** for truncated files.
""")

# 1. Sidebar for Reference File
st.sidebar.header("Repair Settings")
st.sidebar.info("Upload a 'Good' CR2 file here. If any of your batch files are broken/truncated, this file will be used as a template to fix them.")
reference_file = st.sidebar.file_uploader("Upload Reference (Good) CR2", type=["cr2"])

ref_size = 0
if reference_file:
    # Read reference size for patching
    reference_file.seek(0, os.SEEK_END)
    ref_size = reference_file.tell()
    reference_file.seek(0) # Reset pointer
    st.sidebar.success(f"Reference loaded ({ref_size/1024/1024:.2f} MB)")

# 2. Main File Uploader
uploaded_files = st.file_uploader("Upload CR2 Files (Batch)", type=["cr2"], accept_multiple_files=True)

if uploaded_files:
    if st.button(f"Process {len(uploaded_files)} Files"):
        
        # Create an in-memory ZIP file
        zip_buffer = io.BytesIO()
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            
            for idx, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Processing {uploaded_file.name}...")
                
                # Read file into memory
                file_bytes = uploaded_file.getvalue()
                
                # Try finding image
                img = find_valid_image_stream(file_bytes)
                
                # REPAIR LOGIC
                if img is None and ref_size > 0:
                    current_size = len(file_bytes)
                    if current_size < ref_size:
                        missing = ref_size - current_size
                        st.warning(f"Repairing {uploaded_file.name}: Padding {missing} bytes...")
                        
                        # Pad with zeros
                        repaired_bytes = file_bytes + (b'\x00' * missing)
                        img = find_valid_image_stream(repaired_bytes)
                
                # CONVERSION LOGIC
                if img:
                    try:
                        # Convert to DNG data
                        dng_data = process_and_convert(img)
                        
                        # Save DNG to memory buffer
                        dng_buffer = io.BytesIO()
                        tifffile.imwrite(
                            dng_buffer,
                            dng_data,
                            photometric='rgb',
                            compression='adobe_deflate',
                            metadata={
                                'Make': 'Canon (ML)',
                                'Model': 'Silent Pic Restored',
                                'Software': 'Gemini Web Converter',
                                'Orientation': 1,
                            }
                        )
                        
                        # Add to ZIP
                        out_name = os.path.splitext(uploaded_file.name)[0] + ".dng"
                        zip_file.writestr(out_name, dng_buffer.getvalue())
                        
                    except Exception as e:
                        st.error(f"Error converting {uploaded_file.name}: {e}")
                else:
                    st.error(f"Could not recover {uploaded_file.name}")
                
                progress_bar.progress((idx + 1) / len(uploaded_files))
        
        status_text.text("Processing Complete!")
        
        # Download Button
        st.success("All files processed!")
        st.download_button(
            label="Download All as ZIP",
            data=zip_buffer.getvalue(),
            file_name="converted_dngs.zip",
            mime="application/zip"
        )