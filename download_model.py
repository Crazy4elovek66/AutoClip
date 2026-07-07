import os
import urllib.request

MODEL_FILES = {
    "deploy.prototxt": "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt",
    "res10_300x300_ssd_iter_140000.caffemodel": "https://raw.githubusercontent.com/opencv/opencv_3rdparty/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"
}

def main():
    for filename, url in MODEL_FILES.items():
        if os.path.exists(filename):
            print(f"Файл {filename} уже существует.")
        else:
            print(f"Скачивание {filename} с {url}...")
            try:
                urllib.request.urlretrieve(url, filename)
                print(f"Успешно скачан {filename}.")
            except Exception as e:
                print(f"Ошибка при скачивании {filename}: {e}")

if __name__ == "__main__":
    main()
