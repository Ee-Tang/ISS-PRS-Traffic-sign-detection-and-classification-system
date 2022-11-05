from io import StringIO
from pathlib import Path
import streamlit as st
import time
import os
import sys
import argparse
from PIL import Image
from predict import predict


if __name__ == '__main__':
    path = ""
    file_name = ""
    mode = ""
    st.title('Traffic Situation Detection')

    source = ("Picture Detection", "Video Detection")
    source_index = st.sidebar.selectbox("Choose Input", range(
        len(source)), format_func=lambda x: source[x])

    if source_index == 0:
        mode = "predict"
        uploaded_file = st.sidebar.file_uploader(
            "Upload Picture", type=['png', 'jpeg', 'jpg'])
        if uploaded_file is not None:
            is_valid = True
            with st.spinner(text='Resource Loading...'):
                st.sidebar.image(uploaded_file)
                picture = Image.open(uploaded_file)
                picture = picture.convert('RGB')
                picture = picture.save(f'data/images/{uploaded_file.name}')
                path = f'data/images/{uploaded_file.name}'
                file_name = uploaded_file.name
        else:
            is_valid = False
    else:
        mode = "video"
        uploaded_file = st.sidebar.file_uploader("Upload Video", type=['mp4', 'avi'])
        if uploaded_file is not None:
            is_valid = True
            with st.spinner(text='Resource Loading...'):
                st.sidebar.video(uploaded_file)
                with open(os.path.join("data", "videos", uploaded_file.name), "wb") as f:
                    f.write(uploaded_file.getbuffer())
                path = f'data/videos/{uploaded_file.name}'
                file_name = uploaded_file.name
        else:
            is_valid = False

    if is_valid:
        print('valid')
        if st.button('Start Detection'):

            predict(mode, file_name)

            if source_index == 0:
                with st.spinner(text='Preparing Images'):
                    st.image("./data/images_out/" + file_name)

                    st.balloons()
            else:
                with st.spinner(text='Preparing Video'):
                    st.video("./data/videos_out/" + file_name)

                    st.balloons()
